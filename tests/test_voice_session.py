"""Offline orchestration tests for VoiceSession.

Everything here is network-free and discord-free: a NullReceiver replays
scripted AudioChunks, a ScriptedStt yields fixed transcripts, and a
ScriptedIntentParser maps them to real registered commands. We patch the
permission helper (as tests/test_voice_dispatch.py does) so dispatch reaches the
handlers.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from discord_bot.voice.receive import AudioChunk, NullReceiver, VoiceReceiver
from discord_bot.voice.stt import ScriptedStt
from discord_bot.voice.intent import ScriptedIntentParser
from discord_bot.voice.dispatch import Dispatcher, DispatchContext
from discord_bot.voice.registry import build_default_registry
from discord_bot.voice.session import VoiceSession, VoiceSessionConfig


USER_A = 5
USER_B = 9


def _chunk(user_id: int) -> AudioChunk:
    # ~10 ms of stereo 48 kHz 16-bit PCM (1920 bytes) so to_stt_format yields a
    # non-empty mono/16 kHz buffer. Content is irrelevant (ScriptedStt ignores).
    pcm = (b"\x10\x00" * 2) * 480  # 480 stereo frames
    return AudioChunk(user_id=user_id, pcm=pcm, sample_rate=48000, channels=2)


def _make_ctx_factory():
    def make_ctx(user_id: int) -> DispatchContext:
        bot = MagicMock()
        bot.db.modify_user_dkp = AsyncMock()
        bot.db.bank_withdraw = AsyncMock()
        return DispatchContext(
            bot=bot, interaction=MagicMock(), guild_id=111, actor_id=user_id
        )

    return make_ctx


@pytest.mark.asyncio
async def test_session_parses_and_dispatches_in_order():
    receiver = NullReceiver([_chunk(USER_A), _chunk(USER_A), _chunk(USER_B)])
    stt = ScriptedStt(["award 10 to him", "withdraw 2 iron"])
    parser = ScriptedIntentParser(
        [
            ("award", ("award_dkp", {"target": "<@5>", "amount": 10})),
            ("withdraw", ("bank_withdraw", {"item_name": "Iron", "quantity": 2})),
        ]
    )
    registry = build_default_registry()
    dispatcher = Dispatcher(registry)

    results = []

    async def on_result(user_id, intent, result):
        results.append((user_id, intent, result))

    session = VoiceSession(
        receiver=receiver,
        stt=stt,
        intent_parser=parser,
        registry=registry,
        dispatcher=dispatcher,
        make_ctx=_make_ctx_factory(),
        on_result=on_result,
    )

    with patch("discord_bot.utils.is_officer", AsyncMock(return_value=True)):
        await session.run(voice_channel=None)

    # Two utterances grouped per speaker (PTT speaking events), in order.
    assert [r[0] for r in results] == [USER_A, USER_B]
    assert [r[1].command_name for r in results] == ["award_dkp", "bank_withdraw"]
    # award_dkp is non-destructive -> ran to completion.
    assert results[0][2].status == "ok"
    # bank_withdraw is destructive -> gated behind confirmation, not auto-run.
    assert results[1][2].status == "needs_confirmation"


@pytest.mark.asyncio
async def test_session_ptt_groups_audio_per_speaker():
    # A speaks 3 chunks, then B speaks 2 chunks -> exactly two utterances.
    chunks = [_chunk(USER_A)] * 3 + [_chunk(USER_B)] * 2
    receiver = NullReceiver(chunks)

    seen_lengths = []

    def record(pcm, rate):
        seen_lengths.append(len(pcm))
        return "noop please"

    stt = ScriptedStt(record)
    parser = ScriptedIntentParser([])  # everything -> no-match
    registry = build_default_registry()
    dispatcher = Dispatcher(registry)

    results = []

    async def on_result(user_id, intent, result):
        results.append((user_id, intent, result))

    session = VoiceSession(
        receiver=receiver,
        stt=stt,
        intent_parser=parser,
        registry=registry,
        dispatcher=dispatcher,
        make_ctx=_make_ctx_factory(),
        on_result=on_result,
    )

    await session.run(voice_channel=None)

    # One finalize per speaker run; A's utterance carries 3 chunks of audio, B's 2.
    assert len(seen_lengths) == 2
    assert seen_lengths[0] == int(seen_lengths[1] * 3 / 2)
    assert [r[0] for r in results] == [USER_A, USER_B]
    # Unmatched transcript -> unknown_command, still delivered.
    assert all(r[2].status == "unknown_command" for r in results)


@pytest.mark.asyncio
async def test_session_metering_cap_stops_and_notifies():
    receiver = NullReceiver([_chunk(USER_A), _chunk(USER_A), _chunk(USER_B)])
    stt = ScriptedStt(["award 10 to him", "withdraw 2 iron"])
    parser = ScriptedIntentParser(
        [("award", ("award_dkp", {"target": "<@5>", "amount": 10}))]
    )
    registry = build_default_registry()
    dispatcher = Dispatcher(registry)

    results = []
    notices = []

    async def on_result(user_id, intent, result):
        results.append((user_id, intent, result))

    async def on_notice(message):
        notices.append(message)

    async def meter(minutes):
        # Immediately over the cap.
        return "capped"

    session = VoiceSession(
        receiver=receiver,
        stt=stt,
        intent_parser=parser,
        registry=registry,
        dispatcher=dispatcher,
        make_ctx=_make_ctx_factory(),
        on_result=on_result,
        on_notice=on_notice,
        meter=meter,
    )

    with patch("discord_bot.utils.is_officer", AsyncMock(return_value=True)):
        await session.run(voice_channel=None)

    # Capped on the first utterance: nothing dispatched, a notice was emitted,
    # and the session stopped before touching user B's audio.
    assert results == []
    assert len(notices) == 1
    assert session._stopped is True


class _NoStopReceiver(VoiceReceiver):
    """Fires on_speaking_start for each speaker but NEVER on_speaking_stop
    (simulates a dropped stop event / abrupt disconnect). The session must still
    flush the residual buffer at stream end, or the final utterance is lost."""

    def __init__(self, chunks):
        super().__init__()
        self._chunks = list(chunks)
        self._idx = 0
        self._started = False
        self._cur = None

    async def start(self, voice_channel=None):
        self._idx = 0
        self._started = True
        self._cur = None

    async def stop(self):
        self._started = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._started or self._idx >= len(self._chunks):
            raise StopAsyncIteration
        chunk = self._chunks[self._idx]
        self._idx += 1
        if chunk.user_id != self._cur:
            self._cur = chunk.user_id
            await self._emit_speaking_start(chunk.user_id)
        await self._emit_audio(chunk)
        return chunk


@pytest.mark.asyncio
async def test_session_flushes_residual_buffer_when_stop_event_missing():
    # Regression: a speaker whose speaking_stop never fires must still have their
    # final utterance flushed at stream end (not dropped, and not skipped because
    # the VAD fallback only runs when no speaking event ever fired).
    receiver = _NoStopReceiver([_chunk(USER_A), _chunk(USER_A)])
    stt = ScriptedStt(["award 10 to him"])
    parser = ScriptedIntentParser(
        [("award", ("award_dkp", {"target": "<@5>", "amount": 10}))]
    )
    registry = build_default_registry()
    dispatcher = Dispatcher(registry)

    results = []

    async def on_result(user_id, intent, result):
        results.append((user_id, intent, result))

    session = VoiceSession(
        receiver=receiver,
        stt=stt,
        intent_parser=parser,
        registry=registry,
        dispatcher=dispatcher,
        make_ctx=_make_ctx_factory(),
        on_result=on_result,
    )

    with patch("discord_bot.utils.is_officer", AsyncMock(return_value=True)):
        await session.run(voice_channel=None)

    assert [r[0] for r in results] == [USER_A]
    assert results[0][1].command_name == "award_dkp"
    assert results[0][2].status == "ok"


@pytest.mark.asyncio
async def test_session_needs_confirmation_delivered_not_autorun():
    receiver = NullReceiver([_chunk(USER_A)])
    stt = ScriptedStt(["deduct 5"])
    parser = ScriptedIntentParser(
        [("deduct", ("deduct_dkp", {"target": "<@5>", "amount": 5}))]
    )
    registry = build_default_registry()
    dispatcher = Dispatcher(registry)

    make_ctx = _make_ctx_factory()
    captured_ctx = {}

    def wrapped_make_ctx(user_id):
        ctx = make_ctx(user_id)
        captured_ctx["ctx"] = ctx
        return ctx

    results = []

    async def on_result(user_id, intent, result):
        results.append((user_id, intent, result))

    session = VoiceSession(
        receiver=receiver,
        stt=stt,
        intent_parser=parser,
        registry=registry,
        dispatcher=dispatcher,
        make_ctx=wrapped_make_ctx,
        on_result=on_result,
    )

    with patch("discord_bot.utils.is_officer", AsyncMock(return_value=True)):
        await session.run(voice_channel=None)

    assert len(results) == 1
    assert results[0][2].status == "needs_confirmation"
    assert results[0][2].confirm_summary
    # Destructive handler must NOT have run (no auto-confirm).
    captured_ctx["ctx"].bot.db.modify_user_dkp.assert_not_called()
