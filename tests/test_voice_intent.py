import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from discord_bot.voice import (
    ClaudeIntentParser,
    ScriptedIntentParser,
    build_default_registry,
)
from discord_bot.voice.intent import NO_MATCH_TOOL_NAME


@pytest.fixture
def registry():
    return build_default_registry()


def _tool_use_block(name, input_):
    block = MagicMock()
    block.type = "tool_use"
    block.name = name
    block.input = input_
    return block


def _patch_anthropic(blocks):
    """Install a fake ``anthropic`` module whose client returns ``blocks`` and
    record the kwargs passed to messages.create. Returns (module, captured)."""
    captured = {}

    async def _create(**kwargs):
        captured.update(kwargs)
        msg = MagicMock()
        msg.content = blocks
        return msg

    client = MagicMock()
    client.messages.create = _create
    module = types.ModuleType("anthropic")
    module.AsyncAnthropic = MagicMock(return_value=client)
    return module, captured


@pytest.mark.asyncio
async def test_claude_decline_yields_no_match(registry):
    module, captured = _patch_anthropic(
        [_tool_use_block(NO_MATCH_TOOL_NAME, {"reason": "off topic"})]
    )
    with patch.dict(sys.modules, {"anthropic": module}):
        parser = ClaudeIntentParser(api_key="x")
        result = await parser.parse("what is the weather in Paris", registry)

    assert result.command_name is None
    assert result.args == {}
    # The decline pseudo-tool must be offered to the model alongside real ones.
    tool_names = {t["name"] for t in captured["tools"]}
    assert NO_MATCH_TOOL_NAME in tool_names
    assert "award_dkp" in tool_names


@pytest.mark.asyncio
async def test_claude_real_command_still_maps(registry):
    module, _ = _patch_anthropic(
        [_tool_use_block("award_dkp", {"target": "<@7>", "amount": 5})]
    )
    with patch.dict(sys.modules, {"anthropic": module}):
        parser = ClaudeIntentParser(api_key="x")
        result = await parser.parse("give 5 dkp to that guy", registry)

    assert result.command_name == "award_dkp"
    assert result.args == {"target": "<@7>", "amount": 5}


@pytest.mark.asyncio
async def test_scripted_match(registry):
    parser = ScriptedIntentParser(
        [("give him", ("award_dkp", {"target": "<@5>", "amount": 10}))]
    )
    result = await parser.parse("please give him 10 dkp", registry)
    assert result.command_name == "award_dkp"
    assert result.args == {"target": "<@5>", "amount": 10}
    assert result.raw == "please give him 10 dkp"


@pytest.mark.asyncio
async def test_scripted_case_insensitive(registry):
    parser = ScriptedIntentParser(
        [("withdraw", ("bank_withdraw", {"item_name": "Iron", "quantity": 2}))]
    )
    result = await parser.parse("WITHDRAW 2 iron", registry)
    assert result.command_name == "bank_withdraw"


@pytest.mark.asyncio
async def test_scripted_no_match_returns_none(registry):
    parser = ScriptedIntentParser([("award", ("award_dkp", {}))])
    result = await parser.parse("what is the weather", registry)
    assert result.command_name is None
    assert result.args == {}
    assert result.raw == "what is the weather"


@pytest.mark.asyncio
async def test_scripted_first_rule_wins(registry):
    parser = ScriptedIntentParser(
        [
            ("dkp", ("award_dkp", {"first": True})),
            ("dkp", ("deduct_dkp", {"second": True})),
        ]
    )
    result = await parser.parse("change the dkp", registry)
    assert result.command_name == "award_dkp"
    assert result.args == {"first": True}


@pytest.mark.asyncio
async def test_scripted_empty_rules(registry):
    parser = ScriptedIntentParser()
    result = await parser.parse("anything", registry)
    assert result.command_name is None


@pytest.mark.asyncio
async def test_scripted_args_are_copied(registry):
    shared = {"target": "<@1>", "amount": 5}
    parser = ScriptedIntentParser([("go", ("award_dkp", shared))])
    result = await parser.parse("go", registry)
    result.args["amount"] = 999
    # The parser's stored rule must not be mutated.
    assert shared["amount"] == 5
