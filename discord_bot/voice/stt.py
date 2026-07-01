"""Speech-to-text engines for the voice pipeline.

``SttEngine`` is the abstraction: turn a chunk of mono/16-bit/LE PCM into a
transcript string. ``ScriptedStt`` is the deterministic, network-free fake used
by tests. ``DeepgramStt`` / ``FasterWhisperStt`` are the live backends; both
lazy-import their heavy SDK *inside* ``transcribe`` so importing this module is
side-effect-free and requires none of those packages to be installed.

Import-time contract
--------------------
This module imports nothing from Deepgram / faster-whisper / network at module
scope. A missing backend fails loudly at ``transcribe()`` time with an
actionable :class:`SttUnavailable`, never at import.
"""

from __future__ import annotations

import abc
import os
from typing import Callable, Optional, Sequence, Union

__all__ = [
    "SttEngine",
    "ScriptedStt",
    "DeepgramStt",
    "FasterWhisperStt",
    "SttUnavailable",
]


class SttUnavailable(Exception):
    """Raised when a concrete STT backend cannot be used.

    Typically means the optional SDK (``deepgram-sdk`` / ``faster-whisper``) is
    not installed, or no API key is configured. The message always tells the
    operator exactly how to remediate.
    """


class SttEngine(abc.ABC):
    """Abstract speech-to-text engine.

    ``transcribe`` takes **mono, 16-bit signed LE** PCM at ``sample_rate`` Hz
    (16 kHz by default — the canonical output of
    :func:`discord_bot.voice.audio_utils.to_stt_format`) and returns the decoded
    transcript. It returns an empty string when the audio contains no speech.
    """

    @abc.abstractmethod
    async def transcribe(self, pcm: bytes, *, sample_rate: int = 16000) -> str:
        raise NotImplementedError


class ScriptedStt(SttEngine):
    """Deterministic STT for tests — no network, no model.

    Constructed with either a fixed sequence of transcripts (returned in order,
    then ``""`` once exhausted) or a callable ``(pcm, sample_rate) -> str``.
    """

    def __init__(
        self,
        transcripts: Union[Sequence[str], Callable[[bytes, int], str], None] = None,
    ):
        if callable(transcripts):
            self._fn: Optional[Callable[[bytes, int], str]] = transcripts
            self._queue: list[str] = []
        else:
            self._fn = None
            self._queue = list(transcripts or [])
        self._idx = 0

    async def transcribe(self, pcm: bytes, *, sample_rate: int = 16000) -> str:
        if self._fn is not None:
            return self._fn(pcm, sample_rate)
        if self._idx >= len(self._queue):
            return ""
        text = self._queue[self._idx]
        self._idx += 1
        return text


class DeepgramStt(SttEngine):
    """Deepgram (Nova-3) batch/prerecorded STT — lazy, optional.

    The Deepgram SDK is imported *inside* :meth:`transcribe`, so importing this
    module never requires ``deepgram-sdk``. The 16 kHz mono PCM is wrapped as a
    prerecorded (batch) request. If the SDK is missing or no key is configured,
    raises :class:`SttUnavailable` with an install/config hint.
    """

    _INSTALL_HINT = (
        "Deepgram STT requires the optional 'deepgram-sdk' package, which is "
        "NOT installed.\n"
        "  Install:  pip install deepgram-sdk\n"
        "  Configure: set DEEPGRAM_API_KEY in the environment.\n"
        "  Voice STT is lazy-imported; the rest of the bot runs without it."
    )

    def __init__(self, *, api_key: Optional[str] = None, model: str = "nova-3"):
        self.api_key = api_key or os.environ.get("DEEPGRAM_API_KEY")
        self.model = model

    async def transcribe(self, pcm: bytes, *, sample_rate: int = 16000) -> str:  # pragma: no cover - live path
        if not self.api_key:
            raise SttUnavailable(
                "Deepgram STT needs DEEPGRAM_API_KEY set in the environment."
            )
        try:
            from deepgram import (  # type: ignore
                DeepgramClient,
                PrerecordedOptions,
                FileSource,
            )
        except Exception as exc:  # ImportError or incompat surfaced at import
            raise SttUnavailable(self._INSTALL_HINT) from exc

        client = DeepgramClient(self.api_key)
        source: "FileSource" = {"buffer": pcm}
        options = PrerecordedOptions(
            model=self.model,
            smart_format=True,
            encoding="linear16",
            sample_rate=sample_rate,
            channels=1,
        )
        response = await client.listen.asyncrest.v("1").transcribe_file(
            source, options
        )
        try:
            return (
                response.results.channels[0].alternatives[0].transcript or ""
            ).strip()
        except (AttributeError, IndexError):
            return ""


class FasterWhisperStt(SttEngine):
    """Local faster-whisper STT — lazy, optional.

    Loads a local CTranslate2 Whisper model on first use. ``faster_whisper`` is
    imported *inside* :meth:`transcribe` (and the model cached), so importing
    this module never requires it. Missing package -> :class:`SttUnavailable`.
    """

    _INSTALL_HINT = (
        "Local Whisper STT requires the optional 'faster-whisper' package, "
        "which is NOT installed.\n"
        "  Install:  pip install faster-whisper\n"
        "  Voice STT is lazy-imported; the rest of the bot runs without it."
    )

    def __init__(self, *, model_size: str = "base", device: str = "cpu"):
        self.model_size = model_size
        self.device = device
        self._model = None

    async def transcribe(self, pcm: bytes, *, sample_rate: int = 16000) -> str:  # pragma: no cover - live path
        try:
            import numpy as np  # type: ignore
            from faster_whisper import WhisperModel  # type: ignore
        except Exception as exc:
            raise SttUnavailable(self._INSTALL_HINT) from exc

        if self._model is None:
            self._model = WhisperModel(self.model_size, device=self.device)

        # 16-bit signed LE PCM -> float32 in [-1, 1], which Whisper expects.
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _info = self._model.transcribe(audio, language="en")
        return " ".join(seg.text.strip() for seg in segments).strip()
