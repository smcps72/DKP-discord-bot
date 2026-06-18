import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from discord_bot.voice import (
    CommandRegistry,
    VoiceCommand,
    IntentResult,
    Dispatcher,
    DispatchContext,
    DispatchResult,
)


def _ctx():
    return DispatchContext(
        bot=MagicMock(),
        interaction=MagicMock(),
        guild_id=111,
        actor_id=222,
    )


def _registry(handler, *, destructive=False, permission="officer"):
    reg = CommandRegistry()
    reg.register(
        VoiceCommand(
            name="do_thing",
            description="d",
            input_schema={
                "type": "object",
                "properties": {
                    "amount": {"type": "integer", "minimum": 1},
                    "mode": {"type": "string", "enum": ["a", "b"]},
                },
                "required": ["amount"],
                "additionalProperties": False,
            },
            handler=handler,
            destructive=destructive,
            permission=permission,
        )
    )
    return reg


@pytest.mark.asyncio
async def test_unknown_command():
    reg = _registry(AsyncMock())
    disp = Dispatcher(reg)
    result = await disp.dispatch(IntentResult(command_name=None, args={}), _ctx())
    assert result.status == "unknown_command"

    result = await disp.dispatch(IntentResult(command_name="nope", args={}), _ctx())
    assert result.status == "unknown_command"


@pytest.mark.asyncio
async def test_invalid_args_missing_required():
    reg = _registry(AsyncMock())
    disp = Dispatcher(reg)
    result = await disp.dispatch(IntentResult(command_name="do_thing", args={}), _ctx())
    assert result.status == "invalid_args"
    assert "amount" in result.message


@pytest.mark.asyncio
async def test_invalid_args_wrong_type():
    reg = _registry(AsyncMock())
    disp = Dispatcher(reg)
    result = await disp.dispatch(
        IntentResult(command_name="do_thing", args={"amount": "five"}), _ctx()
    )
    assert result.status == "invalid_args"


@pytest.mark.asyncio
async def test_invalid_args_minimum():
    reg = _registry(AsyncMock())
    disp = Dispatcher(reg)
    result = await disp.dispatch(
        IntentResult(command_name="do_thing", args={"amount": 0}), _ctx()
    )
    assert result.status == "invalid_args"


@pytest.mark.asyncio
async def test_invalid_args_maximum():
    # H1 regression: integer fields with a maximum must reject over-large values
    # BEFORE the permission check or any mutation.
    from discord_bot.voice import build_default_registry

    disp = Dispatcher(build_default_registry())
    result = await disp.dispatch(
        IntentResult(
            command_name="award_dkp",
            args={"target": "<@5>", "amount": 10 ** 12},
        ),
        _ctx(),
    )
    assert result.status == "invalid_args"


@pytest.mark.asyncio
async def test_invalid_args_enum():
    reg = _registry(AsyncMock())
    disp = Dispatcher(reg)
    result = await disp.dispatch(
        IntentResult(command_name="do_thing", args={"amount": 1, "mode": "z"}), _ctx()
    )
    assert result.status == "invalid_args"


@pytest.mark.asyncio
async def test_invalid_args_additional_property():
    reg = _registry(AsyncMock())
    disp = Dispatcher(reg)
    result = await disp.dispatch(
        IntentResult(command_name="do_thing", args={"amount": 1, "extra": 1}), _ctx()
    )
    assert result.status == "invalid_args"


@pytest.mark.asyncio
async def test_denied_when_permission_fails():
    handler = AsyncMock()
    reg = _registry(handler, permission="officer")
    disp = Dispatcher(reg)
    with patch("discord_bot.utils.is_officer", AsyncMock(return_value=False)):
        result = await disp.dispatch(
            IntentResult(command_name="do_thing", args={"amount": 1}), _ctx()
        )
    assert result.status == "denied"
    handler.assert_not_called()


@pytest.mark.asyncio
async def test_anyone_permission_always_allowed():
    handler = AsyncMock(return_value=DispatchResult(status="ok", message="done"))
    reg = _registry(handler, permission="anyone")
    disp = Dispatcher(reg)
    result = await disp.dispatch(
        IntentResult(command_name="do_thing", args={"amount": 1}), _ctx()
    )
    assert result.status == "ok"
    handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_ok_path():
    handler = AsyncMock(return_value=DispatchResult(status="ok", message="done"))
    reg = _registry(handler, permission="officer")
    disp = Dispatcher(reg)
    with patch("discord_bot.utils.is_officer", AsyncMock(return_value=True)):
        result = await disp.dispatch(
            IntentResult(command_name="do_thing", args={"amount": 3}), _ctx()
        )
    assert result.status == "ok"
    handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_destructive_needs_confirmation_then_confirmed():
    handler = AsyncMock(return_value=DispatchResult(status="ok", message="done"))
    reg = _registry(handler, destructive=True, permission="officer")
    disp = Dispatcher(reg)
    intent = IntentResult(command_name="do_thing", args={"amount": 2})

    with patch("discord_bot.utils.is_officer", AsyncMock(return_value=True)):
        first = await disp.dispatch(intent, _ctx(), confirmed=False)
        assert first.status == "needs_confirmation"
        assert first.confirm_summary
        handler.assert_not_called()

        second = await disp.dispatch(intent, _ctx(), confirmed=True)
        assert second.status == "ok"
        handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_handler_exception_becomes_error():
    handler = AsyncMock(side_effect=RuntimeError("boom"))
    reg = _registry(handler, permission="anyone")
    disp = Dispatcher(reg)
    result = await disp.dispatch(
        IntentResult(command_name="do_thing", args={"amount": 1}), _ctx()
    )
    assert result.status == "error"
    assert "boom" in result.message
