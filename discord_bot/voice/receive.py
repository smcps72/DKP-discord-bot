"""Swappable Discord voice-receive abstraction (Phase-0 de-risk spike).

Real-time *voice receive* is the single fragile component of the
voice-controlled AI platform: it is **not** in discord.py mainline, the best
low-migration option (``discord-ext-voice-recv``) is alpha and currently broken
against discord.py 2.7.1 under Discord's DAVE E2EE, and the robust alternative
(Pycord's Sinks API) is a full library switch.

To keep that risk isolated from the rest of the platform, *everything*
downstream of the microphone talks to the :class:`VoiceReceiver` contract
defined here. The concrete backend (voice-recv adapter, Pycord adapter, or the
no-network :class:`NullReceiver` fake) can be swapped without touching the
STT -> VAD -> intent -> dispatch pipeline.

Import-time contract
--------------------
This module is **import-clean and network-free**: it imports nothing from
``discord`` and nothing from the optional voice-receive extension at module
scope. The optional backends are *lazy-imported inside methods* so that:

* importing :mod:`discord_bot.voice` never requires the extension to be
  installed, and
* a missing/incompatible backend fails loudly at ``start()`` with an
  actionable :class:`VoiceReceiveUnavailable`, not at import.

See ``Documentation/voice-ai/SPIKE.md`` for the go/no-go writeup and the
boundary between what is validated offline (here) and what still needs a live
DAVE channel.
"""

from __future__ import annotations

import abc
import asyncio
import time
from dataclasses import dataclass, field
from typing import AsyncIterator, Awaitable, Callable, List, Optional, Sequence

__all__ = [
    "AudioChunk",
    "VoiceReceiver",
    "VoiceRecvAdapter",
    "PycordSinkAdapter",
    "NullReceiver",
    "VoiceReceiveUnavailable",
    "SpeakingHook",
]


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #
class VoiceReceiveUnavailable(Exception):
    """Raised when a concrete receive backend cannot be started.

    Typically means the optional ``discord-ext-voice-recv`` extension is not
    installed, or is installed but incompatible with the running discord.py
    (e.g. discord.py 2.7.1 + DAVE E2EE, which is the broken regime). The
    message should always tell the operator exactly how to remediate.
    """


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #
@dataclass
class AudioChunk:
    """One contiguous block of PCM audio attributed to a single speaker.

    Discord delivers **48 kHz, 16-bit, signed little-endian, stereo** PCM per
    speaking user. Downstream VAD/STT generally want **16 kHz mono**; conversion
    lives in :mod:`discord_bot.voice.audio_utils` (``to_stt_format``) rather than
    here, so the receive layer stays a dumb transport.

    Attributes
    ----------
    user_id:
        Discord user/member id of the speaker this audio belongs to.
    pcm:
        Raw signed 16-bit little-endian PCM samples. Interleaved if
        ``channels == 2`` (L, R, L, R, ...).
    sample_rate:
        Samples per second per channel (48000 straight off Discord).
    channels:
        1 (mono) or 2 (stereo). Discord native is 2.
    timestamp:
        ``time.time()`` (epoch seconds) at which the chunk was received/emitted.
        Used for ordering and for trailing-silence / utterance timing; it is a
        wall-clock receive time, not a media PTS.
    """

    user_id: int
    pcm: bytes
    sample_rate: int = 48000
    channels: int = 2
    timestamp: float = field(default_factory=time.time)


# A speaking hook is an optional (sync or async) callback taking a user id.
SpeakingHook = Callable[[int], Optional[Awaitable[None]]]


# --------------------------------------------------------------------------- #
# The contract
# --------------------------------------------------------------------------- #
class VoiceReceiver(abc.ABC):
    """Abstract per-user voice receive backend.

    Lifecycle
    ---------
    1. Construct the receiver (cheap, no network).
    2. ``await receiver.start(voice_channel)`` — connect/attach to the channel
       and begin capturing. May raise :class:`VoiceReceiveUnavailable` if the
       backend is unusable in this environment.
    3. Consume per-user :class:`AudioChunk`s, either by:
         * ``async for chunk in receiver:`` (async-iterator interface), or
         * registering an ``on_audio`` callback via :meth:`add_audio_callback`.
       A backend MUST support the async-iterator interface; the callback
       interface is an additional convenience and MAY be a thin wrapper over it.
    4. ``await receiver.stop()`` — stop capture, disconnect, and terminate the
       async iterator (it raises ``StopAsyncIteration`` / the ``async for``
       loop ends).

    Speaking hooks
    --------------
    :meth:`on_speaking_start` / :meth:`on_speaking_stop` register callbacks
    fired (best-effort) when Discord signals a user begins/stops transmitting.
    These drive push-to-talk gating and utterance segmentation. Backends that
    cannot produce real speaking events (e.g. a record-then-callback Pycord
    sink) MUST document that the hooks will not fire and downstream code must
    fall back to energy VAD (:mod:`discord_bot.voice.vad`).

    Threading / async
    -----------------
    All public methods are ``async`` and must be safe to ``await`` from the
    bot's event loop. Backends bridging a thread/callback world (voice-recv
    sinks run off-loop) are responsible for marshalling onto the loop (e.g.
    ``loop.call_soon_threadsafe`` feeding an ``asyncio.Queue``).
    """

    def __init__(self) -> None:
        self._on_speaking_start: List[SpeakingHook] = []
        self._on_speaking_stop: List[SpeakingHook] = []
        self._on_audio: List[Callable[[AudioChunk], Optional[Awaitable[None]]]] = []

    # -- lifecycle -------------------------------------------------------- #
    @abc.abstractmethod
    async def start(self, voice_channel) -> None:
        """Attach to ``voice_channel`` and begin capturing per-user audio.

        ``voice_channel`` is a ``discord.VoiceChannel`` (or compatible). Kept
        untyped so this module imports without ``discord``.

        Raises
        ------
        VoiceReceiveUnavailable
            If the concrete backend is not installed or not usable here.
        """

    @abc.abstractmethod
    async def stop(self) -> None:
        """Stop capture, release the connection, and end the async iterator."""

    # -- per-user audio stream (async-iterator interface) ----------------- #
    @abc.abstractmethod
    def __aiter__(self) -> "AsyncIterator[AudioChunk]":
        ...

    @abc.abstractmethod
    async def __anext__(self) -> AudioChunk:
        ...

    # -- callback registration (default implementations) ------------------ #
    def add_audio_callback(
        self, cb: Callable[[AudioChunk], Optional[Awaitable[None]]]
    ) -> None:
        """Register a callback invoked for every emitted :class:`AudioChunk`."""
        self._on_audio.append(cb)

    def on_speaking_start(self, cb: SpeakingHook) -> None:
        """Register a hook fired when a user starts transmitting."""
        self._on_speaking_start.append(cb)

    def on_speaking_stop(self, cb: SpeakingHook) -> None:
        """Register a hook fired when a user stops transmitting."""
        self._on_speaking_stop.append(cb)

    # -- helpers for backends to fire registered hooks -------------------- #
    @staticmethod
    async def _fire(hooks: Sequence[Callable], *args) -> None:
        """Invoke each hook, awaiting any that return awaitables.

        Sync and async callbacks are both supported so adapters and tests can
        register either style.
        """
        for hook in hooks:
            result = hook(*args)
            if asyncio.iscoroutine(result):
                await result

    async def _emit_speaking_start(self, user_id: int) -> None:
        await self._fire(self._on_speaking_start, user_id)

    async def _emit_speaking_stop(self, user_id: int) -> None:
        await self._fire(self._on_speaking_stop, user_id)

    async def _emit_audio(self, chunk: AudioChunk) -> None:
        await self._fire(self._on_audio, chunk)


# --------------------------------------------------------------------------- #
# Backend 1: discord-ext-voice-recv adapter (lazy, optional)
# --------------------------------------------------------------------------- #
class VoiceRecvAdapter(VoiceReceiver):
    """Adapter over ``discord-ext-voice-recv`` (keeps discord.py).

    This is the *recommended* live backend because it avoids a full library
    switch. It is, however, **alpha, unmaintained since ~June 2025, and broken
    against discord.py 2.7.1 under DAVE E2EE** (voice-recv issue #53). If you
    intend to use it live, pin **discord.py <= 2.6.4** (see ``SPIKE.md``).

    The extension is *lazy-imported inside* :meth:`start`. If it cannot be
    imported, :meth:`start` raises :class:`VoiceReceiveUnavailable` with
    install + pin guidance. Nothing here imports ``discord`` or the extension
    at module scope, so the spike's offline tests run with neither installed.

    Mapping (for when it IS available):
      * Connect with ``voice_recv.VoiceRecvClient`` as the ``cls`` of
        ``channel.connect``.
      * Install a sink whose ``write(user, voice_data)`` pushes an
        :class:`AudioChunk` (48 kHz/16-bit/stereo) onto an ``asyncio.Queue``
        via ``loop.call_soon_threadsafe`` (sinks run off the event loop).
      * Bridge the extension's ``voice_recv`` speaking events onto
        :meth:`_emit_speaking_start` / :meth:`_emit_speaking_stop`.
      * :meth:`__anext__` pops from the queue; :meth:`stop` disconnects and
        pushes a sentinel so the iterator terminates.
    """

    _INSTALL_HINT = (
        "Real-time Discord voice receive requires the optional "
        "'discord-ext-voice-recv' extension, which is NOT installed.\n"
        "  Install:  pip install discord-ext-voice-recv\n"
        "  IMPORTANT: this extension is alpha and currently BROKEN against "
        "discord.py 2.7.1 under Discord's DAVE E2EE (voice-recv issue #53). "
        "This environment has discord.py 2.7.1, i.e. the broken regime. To "
        "capture live audio you must pin 'discord.py<=2.6.4' alongside it.\n"
        "  All offline DSP/VAD/interface behaviour is validated without it; "
        "only live per-user capture needs it. See Documentation/voice-ai/SPIKE.md."
    )

    def __init__(self) -> None:
        super().__init__()
        self._queue: "asyncio.Queue[Optional[AudioChunk]]" = asyncio.Queue()
        self._client = None
        self._started = False

    async def start(self, voice_channel) -> None:  # pragma: no cover - needs live VC
        # Lazy import: never required to import this module / package.
        try:
            from discord.ext import voice_recv  # type: ignore  # noqa: F401
        except Exception as exc:  # ImportError or any incompat surfaced at import
            raise VoiceReceiveUnavailable(self._INSTALL_HINT) from exc

        # The live wiring below is intentionally NOT exercised by the offline
        # spike (no token / no VC here). It documents the intended mapping and
        # is the single place that touches the extension.
        loop = asyncio.get_running_loop()

        class _SpikeSink(voice_recv.AudioSink):  # type: ignore[attr-defined]
            def __init__(self, outer: "VoiceRecvAdapter") -> None:
                super().__init__()
                self._outer = outer
                self._loop = loop

            def wants_opus(self) -> bool:
                # Request decoded PCM (48 kHz/16-bit/stereo), not raw Opus.
                return False

            def write(self, user, data) -> None:  # voice_data carries .pcm
                if user is None:
                    return
                chunk = AudioChunk(
                    user_id=int(getattr(user, "id", 0)),
                    pcm=bytes(getattr(data, "pcm", b"")),
                    sample_rate=48000,
                    channels=2,
                    timestamp=time.time(),
                )
                # Sinks run off the event loop -> marshal onto it.
                self._loop.call_soon_threadsafe(self._outer._queue.put_nowait, chunk)

            def cleanup(self) -> None:
                pass

        self._client = await voice_channel.connect(cls=voice_recv.VoiceRecvClient)

        # Bridge speaking events onto the contract's hooks.
        def _speaking_start(member, *_a):
            loop.create_task(self._emit_speaking_start(int(getattr(member, "id", 0))))

        def _speaking_stop(member, *_a):
            loop.create_task(self._emit_speaking_stop(int(getattr(member, "id", 0))))

        self._client.add_listener(_speaking_start, "voice_member_speaking_start")
        self._client.add_listener(_speaking_stop, "voice_member_speaking_stop")
        self._client.listen(_SpikeSink(self))
        self._started = True

    async def stop(self) -> None:  # pragma: no cover - needs live VC
        if self._client is not None:
            try:
                self._client.stop_listening()
            finally:
                await self._client.disconnect()
            self._client = None
        self._started = False
        # Sentinel terminates any active async-for consumer.
        await self._queue.put(None)

    def __aiter__(self) -> "AsyncIterator[AudioChunk]":
        return self

    async def __anext__(self) -> AudioChunk:  # pragma: no cover - needs live VC
        if not self._started:
            raise StopAsyncIteration
        chunk = await self._queue.get()
        if chunk is None:  # sentinel from stop()
            raise StopAsyncIteration
        await self._emit_audio(chunk)
        return chunk


# --------------------------------------------------------------------------- #
# Backend 2: Pycord Sinks adapter (escape hatch STUB)
# --------------------------------------------------------------------------- #
class PycordSinkAdapter(VoiceReceiver):
    """Escape-hatch adapter over Pycord 2.8.0's Sinks API (STUB).

    Pycord's recording sinks are the *robust* alternative if voice-recv proves
    unworkable, but adopting them is a **full library switch** (Pycord and
    discord.py cannot coexist in one process) and the Sinks model is
    **record-then-callback**: you ``vc.start_recording(sink, callback)``, then on
    ``vc.stop_recording()`` the callback receives the *finished* per-user
    buffers. Consequences for this contract:

      * There is **no live per-chunk stream** and **no real-time speaking
        events** — :meth:`on_speaking_start` / :meth:`on_speaking_stop` will not
        fire; downstream must use energy/silero VAD for segmentation.
      * The async-iterator would yield each user's whole recording once, after
        ``stop()``.

    This class exists to *prove the interface can host both backends*. It is a
    deliberate stub: every operational method raises ``NotImplementedError`` with
    a pointer to the escape-hatch decision in ``SPIKE.md``.
    """

    _NOTE = (
        "PycordSinkAdapter is the documented escape hatch and is not implemented "
        "in the Phase-0 spike. Adopting it is a full library switch from "
        "discord.py to Pycord 2.8.0 and changes the contract to "
        "record-then-callback (no live speaking events). See "
        "Documentation/voice-ai/SPIKE.md (receive-layer decision)."
    )

    async def start(self, voice_channel) -> None:
        raise NotImplementedError(self._NOTE)

    async def stop(self) -> None:
        raise NotImplementedError(self._NOTE)

    def __aiter__(self) -> "AsyncIterator[AudioChunk]":
        return self

    async def __anext__(self) -> AudioChunk:
        raise NotImplementedError(self._NOTE)


# --------------------------------------------------------------------------- #
# Backend 3: NullReceiver — no-network fake for tests / smoke
# --------------------------------------------------------------------------- #
class NullReceiver(VoiceReceiver):
    """In-memory fake that replays a fixed list of :class:`AudioChunk`s.

    Touches no network and no Discord library, so it is the substitute used by
    unit tests and offline smoke runs. On iteration it replays the provided
    chunks in order; if ``fire_speaking_hooks`` is set (default), it also fires
    ``on_speaking_start`` before a speaker's first chunk and ``on_speaking_stop``
    when that speaker's run ends (i.e. the next chunk is a different user, or
    the stream ends) — a faithful-enough stand-in for Discord's speaking events.

    Example
    -------
    >>> r = NullReceiver([AudioChunk(1, b"\\x00\\x00", 48000, 1)])
    >>> await r.start(None)
    >>> async for chunk in r:
    ...     ...
    >>> await r.stop()
    """

    def __init__(
        self,
        chunks: Optional[Sequence[AudioChunk]] = None,
        *,
        fire_speaking_hooks: bool = True,
    ) -> None:
        super().__init__()
        self._chunks: List[AudioChunk] = list(chunks or [])
        self._fire_speaking = fire_speaking_hooks
        self._idx = 0
        self._started = False
        self._current_speaker: Optional[int] = None

    async def start(self, voice_channel=None) -> None:
        self._idx = 0
        self._current_speaker = None
        self._started = True

    async def stop(self) -> None:
        # Emit a trailing speaking_stop if a speaker was active.
        if self._fire_speaking and self._current_speaker is not None:
            await self._emit_speaking_stop(self._current_speaker)
            self._current_speaker = None
        self._started = False

    def __aiter__(self) -> "AsyncIterator[AudioChunk]":
        return self

    async def __anext__(self) -> AudioChunk:
        if not self._started or self._idx >= len(self._chunks):
            # End of replay: close out the active speaker run.
            if self._fire_speaking and self._current_speaker is not None:
                await self._emit_speaking_stop(self._current_speaker)
                self._current_speaker = None
            raise StopAsyncIteration

        chunk = self._chunks[self._idx]
        self._idx += 1

        if self._fire_speaking and chunk.user_id != self._current_speaker:
            if self._current_speaker is not None:
                await self._emit_speaking_stop(self._current_speaker)
            self._current_speaker = chunk.user_id
            await self._emit_speaking_start(chunk.user_id)

        await self._emit_audio(chunk)
        return chunk
