"""Pure, deterministic DSP helpers for the voice pipeline.

These convert Discord's native audio (48 kHz, 16-bit signed LE, **stereo**) into
what VAD/STT want (16 kHz, 16-bit, **mono**). Everything here is synchronous,
side-effect-free, and fully unit-testable on tiny synthetic PCM buffers.

Implementation uses stdlib :mod:`audioop`.

.. note::
   ``audioop`` was **removed from the Python standard library in 3.13**. This
   spike runs on Python 3.12 where it is still present (it emits a
   ``DeprecationWarning``). For production on 3.13+, install the drop-in
   ``audioop-lts`` backport, or replace these helpers with a numpy path (the
   functions are isolated precisely so that swap is local). See SPIKE.md.
"""

from __future__ import annotations

import audioop
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # avoid an import cycle at runtime; only for type hints
    from .receive import AudioChunk

__all__ = ["downmix_stereo_to_mono", "resample", "to_stt_format"]


def downmix_stereo_to_mono(pcm: bytes, width: int = 2) -> bytes:
    """Average interleaved stereo PCM down to mono.

    Parameters
    ----------
    pcm:
        Interleaved signed PCM (L, R, L, R, ...) of sample ``width`` bytes.
    width:
        Bytes per sample (2 = 16-bit). Default 2.

    Returns
    -------
    bytes
        Mono PCM, **half the input length** (one sample per L/R pair).

    Notes
    -----
    ``audioop.tomono`` with equal 0.5 weights performs the standard average
    downmix. Already-mono input would be misinterpreted, so callers must only
    pass true stereo (``channels == 2``).
    """
    return audioop.tomono(pcm, width, 0.5, 0.5)


def resample(
    pcm: bytes,
    from_rate: int,
    to_rate: int,
    channels: int = 1,
    width: int = 2,
) -> bytes:
    """Resample PCM from ``from_rate`` to ``to_rate`` Hz.

    Wraps :func:`audioop.ratecv`. Output length is approximately
    ``len(pcm) * to_rate / from_rate`` (rounded by the rational resampler; not
    exact). A no-op (``from_rate == to_rate``) returns the input unchanged.

    Parameters
    ----------
    pcm:
        Signed PCM. If ``channels == 2`` it must be interleaved.
    from_rate, to_rate:
        Source / target sample rates (Hz).
    channels:
        Number of interleaved channels in ``pcm`` (1 or 2).
    width:
        Bytes per sample.
    """
    if from_rate == to_rate:
        return pcm
    converted, _state = audioop.ratecv(
        pcm, width, channels, from_rate, to_rate, None
    )
    return converted


def to_stt_format(chunk: "AudioChunk", target_rate: int = 16000) -> bytes:
    """Convert an :class:`~discord_bot.voice.receive.AudioChunk` to STT format.

    Produces **mono, ``target_rate`` Hz, 16-bit signed LE** PCM — the canonical
    input for energy VAD and streaming STT (Deepgram / faster-whisper).

    Pipeline: downmix to mono (if stereo) -> resample to ``target_rate``.
    Downmix-before-resample is intentional: it halves the sample count before
    the (more expensive) rate conversion and avoids resampling a channel we are
    about to discard.

    Assumes 16-bit samples (``width = 2``), matching Discord's decoded PCM.
    """
    width = 2
    pcm = chunk.pcm

    if chunk.channels == 2:
        pcm = downmix_stereo_to_mono(pcm, width)
    elif chunk.channels != 1:
        raise ValueError(f"Unsupported channel count: {chunk.channels!r}")

    if chunk.sample_rate != target_rate:
        pcm = resample(
            pcm,
            from_rate=chunk.sample_rate,
            to_rate=target_rate,
            channels=1,
            width=width,
        )
    return pcm
