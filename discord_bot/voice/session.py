"""Voice session orchestration — the testable core of the live-audio pipeline.

A :class:`VoiceSession` wires the swappable :class:`~discord_bot.voice.receive.VoiceReceiver`
into the existing text intent -> dispatch path. Spoken audio becomes the *exact*
same validated, permission-checked command flow as the typed ``/ai`` command —
just with STT + intent parsing in front.

This module imports **nothing from discord** and nothing from any STT/LLM SDK,
so the whole orchestration is unit-testable offline with
:class:`~discord_bot.voice.receive.NullReceiver` + a scripted STT + a scripted
intent parser. The live adapters (voice-recv, Deepgram, faster-whisper, Claude)
all sit behind the abstractions this session consumes.

Segmentation contract
---------------------
Audio arrives as per-speaker :class:`~discord_bot.voice.receive.AudioChunk`s.
Each chunk is converted to STT format (mono / ``target_rate`` / 16-bit) via
:func:`~discord_bot.voice.audio_utils.to_stt_format` and appended to a per-user
buffer. An utterance is closed (finalized -> STT -> intent -> dispatch -> reply)
by one of two mechanisms:

* **Push-to-talk / speaking events (primary).** When the backend fires
  ``on_speaking_start`` / ``on_speaking_stop`` (real Discord voice, and
  ``NullReceiver`` by default), a user's buffer is finalized on their
  ``on_speaking_stop``. This is deterministic: ``NullReceiver`` fires
  ``on_speaking_stop`` for a speaker exactly when their run of chunks ends, so
  replaying ``[A, A, B]`` yields one utterance for A and one for B.

* **Energy VAD (fallback).** Backends that cannot produce speaking events (e.g.
  the Pycord record-then-callback sink) leave the buffers un-finalized; when the
  stream ends, each user's accumulated frames are segmented with
  :class:`~discord_bot.voice.vad.EnergyVAD` and each detected utterance is
  finalized. This path runs only when no speaking events were ever observed, so
  the two mechanisms never double-finalize the same audio.

Metering / cap
--------------
On every finalized utterance the session computes the consumed minutes
(``len(pcm) / (2 * target_rate) / 60``) and calls the optional ``meter``
callback. If ``meter`` reports the configured cap level (default ``"capped"``),
the session emits an out-of-band ``on_notice`` and stops immediately — the
capped utterance is NOT transcribed or dispatched, and no further audio is
processed. Destructive commands are never auto-confirmed: a
``needs_confirmation`` result is delivered to ``on_result`` for the cog to
confirm interactively.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, Dict, Optional

from .audio_utils import to_stt_format
from .dispatch import DispatchContext, DispatchResult, Dispatcher
from .intent import IntentParser, IntentResult
from .receive import AudioChunk, VoiceReceiver
from .stt import SttEngine
from .vad import EnergyVAD

__all__ = ["VoiceSessionConfig", "VoiceSession"]


@dataclass
class VoiceSessionConfig:
    """Tunables for a :class:`VoiceSession`.

    Attributes
    ----------
    frame_bytes:
        Size of one VAD frame in bytes. 20 ms @ 16 kHz mono 16-bit = 640.
    vad_threshold / silence_gap_frames:
        Passed through to the fallback :class:`EnergyVAD`.
    push_to_talk:
        When True, speaking events gate/segment utterances (primary path). The
        EnergyVAD fallback still runs for backends that don't fire them.
    target_rate:
        STT sample rate (Hz). Audio is converted to mono/16-bit at this rate.
    minutes_cap_level:
        The ``meter`` return value that means "stop now" (default ``"capped"``).
    """

    frame_bytes: int = 640
    vad_threshold: int = 500
    silence_gap_frames: int = 10
    push_to_talk: bool = True
    target_rate: int = 16000
    minutes_cap_level: str = "capped"


# Callback type aliases (all async).
MakeCtx = Callable[[int], DispatchContext]
OnResult = Callable[[int, IntentResult, DispatchResult], Awaitable[None]]
OnNotice = Callable[[str], Awaitable[None]]
Meter = Callable[[float], Awaitable[Optional[str]]]


class VoiceSession:
    """Drive a :class:`VoiceReceiver` through the STT -> intent -> dispatch path.

    Parameters
    ----------
    receiver:
        The (swappable) audio-receive backend. ``NullReceiver`` for tests.
    stt:
        Speech-to-text engine (``ScriptedStt`` for tests).
    intent_parser:
        Transcript -> intent mapper (``ScriptedIntentParser`` for tests).
    registry:
        The command registry handed to ``intent_parser.parse`` / dispatch.
    dispatcher:
        Validates / permission-checks / confirms / runs the resolved command.
    make_ctx:
        Builds a per-speaker :class:`DispatchContext` from a user id.
    on_result:
        Async reply delivery: ``(user_id, intent, result) -> None``.
    on_notice:
        Optional async out-of-band notice channel (cap / limit messages).
    meter:
        Optional async usage meter called with minutes consumed per utterance;
        returns the current usage level (e.g. ``"ok"``/``"warn"``/``"capped"``)
        or ``None``.
    config:
        :class:`VoiceSessionConfig`.
    """

    def __init__(
        self,
        receiver: VoiceReceiver,
        stt: SttEngine,
        intent_parser: IntentParser,
        registry,
        dispatcher: Dispatcher,
        make_ctx: MakeCtx,
        on_result: OnResult,
        on_notice: Optional[OnNotice] = None,
        meter: Optional[Meter] = None,
        config: Optional[VoiceSessionConfig] = None,
    ) -> None:
        self.receiver = receiver
        self.stt = stt
        self.intent_parser = intent_parser
        self.registry = registry
        self.dispatcher = dispatcher
        self.make_ctx = make_ctx
        self.on_result = on_result
        self.on_notice = on_notice
        self.meter = meter
        self.config = config or VoiceSessionConfig()

        self._vad = EnergyVAD(
            threshold=self.config.vad_threshold,
            silence_gap_frames=self.config.silence_gap_frames,
        )
        # Per-user STT-format PCM buffers (accumulated between utterances).
        self._buffers: Dict[int, bytearray] = {}
        self._speaking_fired = False
        self._stopped = False

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    async def run(self, voice_channel) -> None:
        """Capture from ``voice_channel`` and process utterances until the
        stream ends, :meth:`stop` is called, or the usage cap is hit.

        Equivalent to :meth:`start_capture` followed by :meth:`consume`; the
        cog splits the two so it can surface a start failure to the invoker
        eagerly and run :meth:`consume` in a background task.
        """
        await self.start_capture(voice_channel)
        await self.consume()

    async def start_capture(self, voice_channel) -> None:
        """Register speaking hooks and start the receiver (may raise)."""
        self._stopped = False
        self._speaking_fired = False
        self._buffers.clear()

        # Speaking events drive the primary (PTT) segmentation path.
        self.receiver.on_speaking_start(self._handle_speaking_start)
        self.receiver.on_speaking_stop(self._handle_speaking_stop)

        await self.receiver.start(voice_channel)

    async def consume(self) -> None:
        """Drain the (already-started) receiver, then stop cleanly."""
        async for chunk in self.receiver:
            if self._stopped:
                break
            self._buffer_chunk(chunk)
            if self._stopped:  # a speaking_stop hook may have capped us
                break

        if not self._stopped:
            if self._speaking_fired:
                # A speaker whose on_speaking_stop never arrived (disconnect or a
                # dropped event) leaves a non-empty buffer that the PTT path
                # never finalized. Flush those residual buffers so their final
                # utterance isn't silently lost. (Finalized speakers were popped
                # from _buffers on speaking_stop, so nothing is double-processed.)
                await self._flush_residual_buffers()
            else:
                # Backends that never fired speaking events: segment each user's
                # accumulated audio with energy VAD.
                await self._flush_with_vad()

        await self.stop()

    async def stop(self) -> None:
        """Stop the receiver and end the loop cleanly (idempotent)."""
        self._stopped = True
        await self.receiver.stop()

    # ------------------------------------------------------------------ #
    # Buffering + speaking hooks
    # ------------------------------------------------------------------ #
    def _buffer_chunk(self, chunk: AudioChunk) -> None:
        pcm = to_stt_format(chunk, target_rate=self.config.target_rate)
        self._buffers.setdefault(chunk.user_id, bytearray()).extend(pcm)

    async def _handle_speaking_start(self, user_id: int) -> None:
        self._speaking_fired = True
        # Begin a fresh utterance for this speaker.
        self._buffers[user_id] = bytearray()

    async def _handle_speaking_stop(self, user_id: int) -> None:
        self._speaking_fired = True
        buf = self._buffers.pop(user_id, None)
        if buf:
            await self._finalize_utterance(user_id, bytes(buf))

    async def _flush_residual_buffers(self) -> None:
        """Finalize any per-user buffers left un-closed when the stream ended.

        These belong to speakers whose ``on_speaking_stop`` never fired; each is
        treated as one trailing utterance.
        """
        for user_id, buf in list(self._buffers.items()):
            if self._stopped:
                return
            self._buffers.pop(user_id, None)
            data = bytes(buf)
            if data:
                await self._finalize_utterance(user_id, data)

    async def _flush_with_vad(self) -> None:
        fb = self.config.frame_bytes
        for user_id, buf in list(self._buffers.items()):
            data = bytes(buf)
            frames = [data[i : i + fb] for i in range(0, len(data), fb)]
            for utterance in self._vad.segment(frames):
                if self._stopped:
                    return
                await self._finalize_utterance(user_id, utterance)
        self._buffers.clear()

    # ------------------------------------------------------------------ #
    # The utterance -> command pipeline (identical to typed /ai downstream)
    # ------------------------------------------------------------------ #
    async def _finalize_utterance(self, user_id: int, pcm: bytes) -> None:
        if self._stopped or not pcm:
            return

        # Meter first so a capped guild never spends STT/LLM budget.
        if self.meter is not None:
            minutes = len(pcm) / (2 * self.config.target_rate) / 60
            level = await self.meter(minutes)
            if level == self.config.minutes_cap_level:
                self._stopped = True
                if self.on_notice is not None:
                    await self.on_notice(
                        "Voice minutes cap reached — stopping the voice session."
                    )
                return

        # stop() may have run during the meter await; don't transcribe/dispatch
        # a command after the session was told to stop.
        if self._stopped:
            return

        text = await self.stt.transcribe(pcm, sample_rate=self.config.target_rate)
        if not text or not text.strip():
            return  # no speech / empty transcript

        intent = await self.intent_parser.parse(text, self.registry)
        ctx = self.make_ctx(user_id)
        # confirmed defaults False: destructive commands come back as
        # needs_confirmation and are delivered to on_result, never auto-run.
        result = await self.dispatcher.dispatch(intent, ctx)
        await self.on_result(user_id, intent, result)
