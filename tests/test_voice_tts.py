"""Offline tests for the TTS engines + speak orchestration seam.

No discord / ElevenLabs / ffmpeg is imported or run: a ScriptedTts produces fake
bytes, a fake voice_client + injected fake ``play`` capture the playback call.
"""

import pytest

import discord_bot.voice.tts as tts_mod
from discord_bot.voice.tts import ScriptedTts, speak
from discord_bot.voice.personas import get_persona


class FakeVoiceClient:
    """Minimal stand-in for a discord voice client (never really plays)."""

    def __init__(self):
        self.played = []

    def is_playing(self):
        return False

    def play(self, source):  # pragma: no cover - not used (we inject play)
        self.played.append(source)


@pytest.mark.asyncio
async def test_scripted_tts_returns_fake_bytes_and_records():
    tts = ScriptedTts()
    persona = get_persona("default")
    out = await tts.synthesize("hello world", persona=persona)
    assert out == b"AUDIO:hello world"
    assert tts.calls == [("hello world", persona)]


@pytest.mark.asyncio
async def test_speak_plays_synthesized_bytes_for_allowed_text():
    tts = ScriptedTts()
    vc = FakeVoiceClient()
    calls = []

    def fake_play(voice_client, audio):
        calls.append((voice_client, audio))

    ok = await speak(vc, tts, "Awarded 10 DKP.", get_persona("default"), play=fake_play)

    assert ok is True
    assert len(calls) == 1
    played_vc, played_audio = calls[0]
    assert played_vc is vc
    # The bytes handed to play are exactly what the engine synthesized.
    assert isinstance(played_audio, bytes)
    assert played_audio == b"AUDIO:" + tts.calls[0][0].encode()


@pytest.mark.asyncio
async def test_speak_returns_false_and_skips_play_on_empty():
    tts = ScriptedTts()
    calls = []

    ok = await speak(FakeVoiceClient(), tts, "   ", get_persona("default"),
                     play=lambda vc, audio: calls.append(audio))

    assert ok is False
    assert calls == []
    assert tts.calls == []  # nothing synthesized


@pytest.mark.asyncio
async def test_speak_returns_false_when_screen_blocks(monkeypatch):
    # Seed the blocklist so the screen gate rejects the text.
    import discord_bot.voice.personas as personas
    monkeypatch.setattr(personas, "BLOCKED_TERMS", {"nope"})

    tts = ScriptedTts()
    calls = []

    ok = await speak(FakeVoiceClient(), tts, "this is a nope phrase",
                     get_persona("default"),
                     play=lambda vc, audio: calls.append(audio))

    assert ok is False
    assert calls == []
    assert tts.calls == []  # blocked before synthesis


@pytest.mark.asyncio
async def test_speak_applies_persona_framing_before_synth():
    tts = ScriptedTts()
    calls = []

    ok = await speak(FakeVoiceClient(), tts, "Awarded 10 DKP.",
                     get_persona("herald"),
                     play=lambda vc, audio: calls.append(audio))

    assert ok is True
    # The synthesized text was persona-framed (prefix applied), core preserved.
    synth_text = tts.calls[0][0]
    assert synth_text.startswith("Hear ye:")
    assert "Awarded 10 DKP." in synth_text
    assert calls[0] == b"AUDIO:" + synth_text.encode()


@pytest.mark.asyncio
async def test_speak_skips_synthesis_when_already_playing():
    # Regression: don't pay for synthesis when the channel is already speaking
    # (the audio would just be dropped). speak() must short-circuit BEFORE synth
    # and signal the drop by returning False.
    class BusyVoiceClient(FakeVoiceClient):
        def is_playing(self):
            return True

    tts = ScriptedTts()
    calls = []

    ok = await speak(BusyVoiceClient(), tts, "Awarded 10 DKP.", get_persona("default"),
                     play=lambda vc, audio: calls.append(audio))

    assert ok is False
    assert calls == []       # play never invoked
    assert tts.calls == []   # nothing synthesized (no wasted API call)


@pytest.mark.asyncio
async def test_speak_awaits_async_play():
    tts = ScriptedTts()
    calls = []

    async def async_play(voice_client, audio):
        calls.append(audio)

    ok = await speak(FakeVoiceClient(), tts, "hi there", get_persona("default"),
                     play=async_play)

    assert ok is True
    assert len(calls) == 1


def test_tts_module_import_is_clean():
    # Importing the module must not pull in elevenlabs / discord / ffmpeg.
    import sys
    assert "elevenlabs" not in sys.modules
    assert tts_mod.ELEVENLABS_MODEL == "eleven_flash_v2_5"
