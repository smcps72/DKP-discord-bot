"""Text-to-speech engines + the speak-back orchestration seam (paid tier).

The bot can speak its command results back into the voice channel. The actual
audio playback needs a *live* Discord voice client (not available offline), so
everything fragile sits behind seams:

* :class:`TtsEngine` is the synthesis abstraction (text -> encoded audio bytes).
* :class:`ScriptedTts` is the deterministic, network-free fake for tests.
* :class:`ElevenLabsTts` is the live backend; it lazy-imports the ElevenLabs SDK
  *inside* :meth:`synthesize` and raises :class:`TtsUnavailable` (with an
  install/config hint) when the SDK or key is missing.
* :func:`speak` is the orchestration seam: sanitize -> screen -> apply persona ->
  synthesize -> play. The play call is injectable so tests drive the whole path
  with a fake ``voice_client`` and a fake ``play`` — no discord / ffmpeg /
  ElevenLabs required.

Import-time contract
--------------------
This module imports nothing from discord / ElevenLabs / ffmpeg at module scope.
The guardrail helpers come from :mod:`discord_bot.voice.personas`, which is also
import-clean.
"""

from __future__ import annotations

import abc
import os
from typing import Awaitable, Callable, Optional

from .personas import (
    Persona,
    apply_persona,
    get_persona,
    sanitize_for_speech,
    screen_text,
)

__all__ = [
    "TtsEngine",
    "ScriptedTts",
    "ElevenLabsTts",
    "TtsUnavailable",
    "speak",
]

# Default ElevenLabs model: low-latency Flash v2.5.
ELEVENLABS_MODEL = "eleven_flash_v2_5"


class TtsUnavailable(Exception):
    """Raised when a concrete TTS backend cannot be used.

    Typically means the optional ``elevenlabs`` SDK is not installed, or no
    ``ELEVENLABS_API_KEY`` is configured. The message always tells the operator
    exactly how to remediate.
    """


class TtsEngine(abc.ABC):
    """Abstract text-to-speech engine.

    ``synthesize`` takes already-sanitised, screened, persona-framed text and
    returns encoded audio bytes (e.g. MP3) suitable for streaming to Discord via
    ffmpeg. ``persona`` selects the voice; ``None`` means the default voice.
    """

    @abc.abstractmethod
    async def synthesize(self, text: str, *, persona: Optional[Persona] = None) -> bytes:
        raise NotImplementedError


class ScriptedTts(TtsEngine):
    """Deterministic TTS for tests — no network, no SDK.

    Returns ``b"AUDIO:" + text.encode()`` and records every call as
    ``(text, persona)`` tuples on :attr:`calls` for assertions.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, Optional[Persona]]] = []

    async def synthesize(self, text: str, *, persona: Optional[Persona] = None) -> bytes:
        self.calls.append((text, persona))
        return b"AUDIO:" + text.encode()


class ElevenLabsTts(TtsEngine):
    """ElevenLabs (Flash v2.5) TTS — lazy, optional.

    The ElevenLabs SDK is imported *inside* :meth:`synthesize`, so importing this
    module never requires ``elevenlabs``. Reads ``ELEVENLABS_API_KEY`` from the
    environment and uses the persona's ``voice_id``. Missing SDK or key raises
    :class:`TtsUnavailable` with an install/config hint.
    """

    _INSTALL_HINT = (
        "TTS speak-back requires the optional 'elevenlabs' package, which is "
        "NOT installed.\n"
        "  Install:  pip install elevenlabs\n"
        "  Configure: set ELEVENLABS_API_KEY in the environment.\n"
        "  TTS is lazy-imported; the rest of the bot runs without it."
    )

    def __init__(self, *, api_key: Optional[str] = None, model: str = ELEVENLABS_MODEL):
        self.api_key = api_key or os.environ.get("ELEVENLABS_API_KEY")
        self.model = model

    async def synthesize(  # pragma: no cover - live path
        self, text: str, *, persona: Optional[Persona] = None
    ) -> bytes:
        if not self.api_key:
            raise TtsUnavailable(
                "ElevenLabs TTS needs ELEVENLABS_API_KEY set in the environment."
            )
        try:
            from elevenlabs.client import ElevenLabs  # type: ignore
        except Exception as exc:  # ImportError or incompat surfaced at import
            raise TtsUnavailable(self._INSTALL_HINT) from exc

        persona = persona or get_persona(None)
        client = ElevenLabs(api_key=self.api_key)
        audio = client.text_to_speech.convert(
            voice_id=persona.voice_id,
            model_id=self.model,
            text=text,
            output_format="mp3_44100_128",
        )
        # The SDK may return a generator of byte chunks or raw bytes.
        if isinstance(audio, (bytes, bytearray)):
            return bytes(audio)
        return b"".join(audio)


# A play callable: (voice_client, audio_bytes) -> None|Awaitable. Injectable so
# tests can avoid discord/ffmpeg entirely.
PlayCallable = Callable[[object, bytes], Optional[Awaitable[None]]]


def _default_play(voice_client, audio: bytes) -> None:  # pragma: no cover - live path
    """Stream ``audio`` to a live Discord voice client via ffmpeg.

    Lazy-imports ``discord`` so this module stays import-clean. Guards against
    overlapping playback. This is the only place that touches ffmpeg/discord.
    """
    import io

    import discord  # lazy

    if voice_client is None or voice_client.is_playing():
        return
    source = discord.FFmpegPCMAudio(io.BytesIO(audio), pipe=True)
    voice_client.play(source)


async def speak(
    voice_client,
    tts: TtsEngine,
    text: str,
    persona: Optional[Persona] = None,
    *,
    play: Optional[PlayCallable] = None,
) -> bool:
    """Speak ``text`` into ``voice_client`` through the full guardrail pipeline.

    Pipeline: :func:`sanitize_for_speech` -> :func:`screen_text` (refuse if
    blocked) -> :func:`apply_persona` -> ``tts.synthesize`` -> ``play``.

    The play step is injectable (``play``); the default builds a
    ``discord.FFmpegPCMAudio`` source and calls ``voice_client.play(...)`` behind
    a lazy import so tests pass a fake ``play`` + fake ``voice_client`` with no
    discord/ffmpeg/ElevenLabs involved.

    Returns ``True`` if audio was synthesized and handed to ``play``; ``False``
    if the text was empty or blocked by the content gate (nothing synthesized,
    ``play`` never called).
    """
    persona = persona or get_persona(None)

    cleaned = sanitize_for_speech(text)
    allowed, _reason = screen_text(cleaned)
    if not allowed:
        return False

    framed = apply_persona(cleaned, persona)
    # Re-screen the framed text as a defensive belt-and-braces check.
    allowed, _reason = screen_text(framed)
    if not allowed:
        return False

    # Don't pay for synthesis if the channel is already speaking — the default
    # play guard would just drop the audio. Check BEFORE synthesizing and signal
    # the drop to the caller (return False) rather than silently wasting the API
    # call. (A future enhancement could queue instead of dropping.)
    is_playing = getattr(voice_client, "is_playing", None)
    if callable(is_playing):
        try:
            if is_playing():
                return False
        except Exception:
            pass

    audio = await tts.synthesize(framed, persona=persona)

    play_fn = play or _default_play
    result = play_fn(voice_client, audio)
    if result is not None and hasattr(result, "__await__"):
        await result
    return True
