import pytest

from discord_bot.voice.stt import ScriptedStt, SttEngine


@pytest.mark.asyncio
async def test_scripted_stt_returns_queued_then_empty():
    stt = ScriptedStt(["hello world", "second"])
    assert isinstance(stt, SttEngine)
    assert await stt.transcribe(b"\x00\x00") == "hello world"
    assert await stt.transcribe(b"\x00\x00") == "second"
    # Exhausted -> empty string (treated as "no speech" downstream).
    assert await stt.transcribe(b"\x00\x00") == ""
    assert await stt.transcribe(b"\x00\x00") == ""


@pytest.mark.asyncio
async def test_scripted_stt_empty_construction():
    stt = ScriptedStt()
    assert await stt.transcribe(b"") == ""


@pytest.mark.asyncio
async def test_scripted_stt_callable():
    stt = ScriptedStt(lambda pcm, rate: f"{len(pcm)}@{rate}")
    assert await stt.transcribe(b"abcd", sample_rate=16000) == "4@16000"
    # Callable is stateless here, so it keeps responding.
    assert await stt.transcribe(b"ab", sample_rate=8000) == "2@8000"
