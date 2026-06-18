"""Tests for the swappable voice-receive abstraction (offline, no Discord)."""

import pytest

from discord_bot.voice.receive import (
    AudioChunk,
    NullReceiver,
    PycordSinkAdapter,
    VoiceRecvAdapter,
    VoiceReceiveUnavailable,
)


def _chunk(user_id, byte=b"\x01\x02"):
    return AudioChunk(user_id=user_id, pcm=byte, sample_rate=48000, channels=2)


# --------------------------------------------------------------------------- #
# NullReceiver — replays chunks and fires speaking hooks
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_null_receiver_replays_chunks():
    chunks = [_chunk(1), _chunk(1), _chunk(2)]
    recv = NullReceiver(chunks)

    seen = []
    recv.add_audio_callback(lambda c: seen.append(c.user_id))

    await recv.start(None)
    collected = [c async for c in recv]
    await recv.stop()

    assert [c.user_id for c in collected] == [1, 1, 2]
    assert seen == [1, 1, 2]


@pytest.mark.asyncio
async def test_null_receiver_fires_speaking_hooks():
    chunks = [_chunk(1), _chunk(1), _chunk(2)]
    recv = NullReceiver(chunks)

    starts, stops = [], []
    recv.on_speaking_start(lambda uid: starts.append(uid))

    async def _stop(uid):  # async hook supported too
        stops.append(uid)

    recv.on_speaking_stop(_stop)

    await recv.start(None)
    async for _ in recv:
        pass
    await recv.stop()

    # User 1 speaks then user 2 -> start(1), stop(1), start(2), stop(2).
    assert starts == [1, 2]
    assert stops == [1, 2]


@pytest.mark.asyncio
async def test_null_receiver_no_hooks_when_disabled():
    recv = NullReceiver([_chunk(1)], fire_speaking_hooks=False)
    starts = []
    recv.on_speaking_start(lambda uid: starts.append(uid))
    await recv.start(None)
    async for _ in recv:
        pass
    await recv.stop()
    assert starts == []


# --------------------------------------------------------------------------- #
# VoiceRecvAdapter — extension absent here -> raises VoiceReceiveUnavailable
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_voice_recv_adapter_unavailable():
    adapter = VoiceRecvAdapter()
    with pytest.raises(VoiceReceiveUnavailable) as exc:
        await adapter.start(object())
    msg = str(exc.value)
    assert "discord-ext-voice-recv" in msg
    assert "2.6.4" in msg  # pin guidance present


# --------------------------------------------------------------------------- #
# PycordSinkAdapter — documented escape-hatch stub
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_pycord_adapter_start_not_implemented():
    with pytest.raises(NotImplementedError):
        await PycordSinkAdapter().start(object())


@pytest.mark.asyncio
async def test_pycord_adapter_anext_not_implemented():
    adapter = PycordSinkAdapter()
    with pytest.raises(NotImplementedError):
        await adapter.__anext__()
