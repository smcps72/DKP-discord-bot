"""Energy-based Voice Activity Detection (stdlib only).

A simple RMS-energy gate that classifies fixed-size PCM frames as speech or
silence and groups consecutive speech frames into utterances. It needs no
model and no network, which makes it the right default for the Phase-0 spike
and a fine fallback when real speaking events are unavailable (e.g. the Pycord
record-then-callback backend).

Production swap
---------------
The recommended production VAD is **silero-vad** (far more robust to background
noise and music). It is intended to slot in behind the *same* interface as
:class:`EnergyVAD` — a class exposing ``is_speech(frame)`` and
``segment(frames)`` — so the pipeline does not change when it is swapped in.
``webrtcvad`` is a lighter alternative. See SPIKE.md.

Frame convention
----------------
Frames are raw 16-bit signed LE mono PCM (the output of
:func:`discord_bot.voice.audio_utils.to_stt_format`). A common choice is 20 ms
frames: at 16 kHz mono 16-bit that is ``16000 * 0.02 * 2 = 640`` bytes.
"""

from __future__ import annotations

import audioop
from typing import List, Sequence

__all__ = ["EnergyVAD"]


class EnergyVAD:
    """Threshold-on-RMS voice activity detector.

    Parameters
    ----------
    threshold:
        RMS value (in raw 16-bit sample units, 0..32767) at or above which a
        frame is considered speech. Default 500 is a reasonable gate for quiet
        rooms; tune per environment.
    silence_gap_frames:
        Number of *consecutive* trailing silence frames that ends an utterance.
        With 20 ms frames, 10 frames ~= 200 ms of trailing silence. Short gaps
        within an utterance (below this many silent frames) are absorbed so a
        natural pause does not split one utterance into two.
    """

    def __init__(self, threshold: int = 500, silence_gap_frames: int = 10) -> None:
        if threshold < 0:
            raise ValueError("threshold must be non-negative")
        if silence_gap_frames < 1:
            raise ValueError("silence_gap_frames must be >= 1")
        self.threshold = threshold
        self.silence_gap_frames = silence_gap_frames

    def is_speech(self, frame: bytes, width: int = 2) -> bool:
        """Return ``True`` if ``frame``'s RMS energy is at/above ``threshold``.

        An empty frame is treated as silence.
        """
        if not frame:
            return False
        return audioop.rms(frame, width) >= self.threshold

    def segment(self, frames: Sequence[bytes], width: int = 2) -> List[bytes]:
        """Group consecutive speech frames into utterances.

        Walks the frame sequence, marking each as speech/silence via
        :meth:`is_speech`. A run of speech (with interior silence runs shorter
        than ``silence_gap_frames`` tolerated) becomes one utterance; a silence
        run of at least ``silence_gap_frames`` closes the current utterance.
        Leading silence is dropped, and trailing silence is trimmed from each
        utterance.

        Parameters
        ----------
        frames:
            Sequence of equal-duration mono PCM frames.
        width:
            Bytes per sample.

        Returns
        -------
        list[bytes]
            One concatenated PCM buffer per detected utterance (empty list if
            no speech is found).
        """
        utterances: List[bytes] = []
        current: List[bytes] = []
        trailing_silence: List[bytes] = []
        in_utterance = False

        for frame in frames:
            if self.is_speech(frame, width):
                if not in_utterance:
                    in_utterance = True
                    current = []
                    trailing_silence = []
                # Absorb any tolerated interior silence back into the utterance.
                if trailing_silence:
                    current.extend(trailing_silence)
                    trailing_silence = []
                current.append(frame)
            else:
                if in_utterance:
                    trailing_silence.append(frame)
                    if len(trailing_silence) >= self.silence_gap_frames:
                        # Close utterance; trailing silence is trimmed (not kept).
                        utterances.append(b"".join(current))
                        current = []
                        trailing_silence = []
                        in_utterance = False
                # else: leading silence, ignore.

        if in_utterance and current:
            utterances.append(b"".join(current))

        return utterances
