import pytest

from discord_bot.voice import (
    ScriptedIntentParser,
    build_default_registry,
)


@pytest.fixture
def registry():
    return build_default_registry()


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
