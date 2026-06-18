"""Unit tests for the offline DSP + VAD helpers (no network, no Discord)."""

import struct

import pytest

from discord_bot.voice import audio_utils
from discord_bot.voice.receive import AudioChunk
from discord_bot.voice.vad import EnergyVAD


def _pcm(samples):
    """Pack a list of int16 samples into signed LE PCM bytes."""
    return struct.pack("<" + "h" * len(samples), *samples)


def _stereo(pairs):
    """Pack (L, R) int16 pairs into interleaved stereo PCM bytes."""
    flat = []
    for left, right in pairs:
        flat.extend((left, right))
    return _pcm(flat)


# --------------------------------------------------------------------------- #
# audio_utils
# --------------------------------------------------------------------------- #
def test_downmix_stereo_to_mono_halves_length():
    stereo = _stereo([(1000, 2000), (3000, 4000), (-1000, -3000)])
    mono = audio_utils.downmix_stereo_to_mono(stereo)
    # 3 stereo frames (12 bytes) -> 3 mono samples (6 bytes).
    assert len(mono) == len(stereo) // 2
    samples = struct.unpack("<3h", mono)
    # tomono averages L and R per frame.
    assert samples == (1500, 3500, -2000)


def test_resample_changes_length_by_ratio():
    # 48 kHz mono -> 16 kHz mono should be ~1/3 the length.
    src = _pcm([100] * 300)  # 300 samples
    out = audio_utils.resample(src, from_rate=48000, to_rate=16000, channels=1)
    ratio = len(out) / len(src)
    assert ratio == pytest.approx(1 / 3, abs=0.05)


def test_resample_noop_when_rates_equal():
    src = _pcm([1, 2, 3, 4])
    assert audio_utils.resample(src, 16000, 16000) == src


def test_to_stt_format_yields_16k_mono():
    # Build a 48 kHz stereo chunk of 480 stereo frames (= 10 ms).
    pairs = [(500, 700)] * 480
    chunk = AudioChunk(
        user_id=42,
        pcm=_stereo(pairs),
        sample_rate=48000,
        channels=2,
    )
    out = audio_utils.to_stt_format(chunk, target_rate=16000)
    # 480 stereo frames @48k -> 480 mono samples @48k -> ~160 samples @16k.
    n_samples = len(out) // 2
    assert n_samples == pytest.approx(160, abs=3)


def test_to_stt_format_mono_passthrough_resamples_only():
    chunk = AudioChunk(user_id=1, pcm=_pcm([10] * 300), sample_rate=48000, channels=1)
    out = audio_utils.to_stt_format(chunk, target_rate=16000)
    assert len(out) // 2 == pytest.approx(100, abs=3)


def test_to_stt_format_rejects_bad_channel_count():
    chunk = AudioChunk(user_id=1, pcm=b"\x00\x00", sample_rate=16000, channels=5)
    with pytest.raises(ValueError):
        audio_utils.to_stt_format(chunk)


# --------------------------------------------------------------------------- #
# EnergyVAD
# --------------------------------------------------------------------------- #
def _silence_frame(n=320):
    return _pcm([0] * n)


def _loud_frame(n=320, amp=8000):
    # Alternating +/- amplitude => high RMS.
    return _pcm([amp if i % 2 == 0 else -amp for i in range(n)])


def test_vad_silence_is_not_speech():
    vad = EnergyVAD(threshold=500)
    assert vad.is_speech(_silence_frame()) is False


def test_vad_empty_frame_is_not_speech():
    assert EnergyVAD().is_speech(b"") is False


def test_vad_loud_is_speech():
    vad = EnergyVAD(threshold=500)
    assert vad.is_speech(_loud_frame()) is True


def test_vad_segment_groups_one_utterance():
    vad = EnergyVAD(threshold=500, silence_gap_frames=3)
    frames = (
        [_silence_frame()] * 2          # leading silence (dropped)
        + [_loud_frame()] * 5           # one utterance
        + [_silence_frame()] * 4        # trailing silence (>= gap -> closes)
    )
    utterances = vad.segment(frames)
    assert len(utterances) == 1
    # 5 loud frames, trailing silence trimmed.
    assert len(utterances[0]) == 5 * len(_loud_frame())


def test_vad_segment_splits_on_long_gap():
    vad = EnergyVAD(threshold=500, silence_gap_frames=2)
    frames = (
        [_loud_frame()] * 3
        + [_silence_frame()] * 3   # >= gap -> closes first utterance
        + [_loud_frame()] * 2
    )
    utterances = vad.segment(frames)
    assert len(utterances) == 2


def test_vad_segment_absorbs_short_interior_gap():
    vad = EnergyVAD(threshold=500, silence_gap_frames=4)
    frames = (
        [_loud_frame()] * 2
        + [_silence_frame()] * 1   # short interior pause, tolerated
        + [_loud_frame()] * 2
    )
    utterances = vad.segment(frames)
    assert len(utterances) == 1
    # Interior silence frame is absorbed -> 5 frames total.
    assert len(utterances[0]) == 5 * len(_loud_frame())


def test_vad_segment_no_speech_returns_empty():
    vad = EnergyVAD(threshold=500)
    assert vad.segment([_silence_frame()] * 5) == []
