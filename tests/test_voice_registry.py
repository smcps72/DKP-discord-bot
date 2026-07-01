import pytest

from discord_bot.voice import (
    CommandRegistry,
    VoiceCommand,
    build_default_registry,
)


async def _noop(args, ctx):
    return None


def _cmd(name="cmd", **kw):
    return VoiceCommand(
        name=name,
        description="desc",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=_noop,
        **kw,
    )


def test_register_and_get():
    reg = CommandRegistry()
    cmd = _cmd("foo")
    reg.register(cmd)
    assert reg.get("foo") is cmd
    assert reg.get("missing") is None


def test_all_returns_registered_commands():
    reg = CommandRegistry()
    reg.register(_cmd("a"))
    reg.register(_cmd("b"))
    names = {c.name for c in reg.all()}
    assert names == {"a", "b"}


def test_duplicate_registration_rejected():
    reg = CommandRegistry()
    reg.register(_cmd("dup"))
    with pytest.raises(ValueError):
        reg.register(_cmd("dup"))


def test_invalid_permission_rejected():
    with pytest.raises(ValueError):
        _cmd("bad", permission="superuser")


def test_tool_specs_shape():
    reg = CommandRegistry()
    reg.register(_cmd("foo"))
    specs = reg.tool_specs()
    assert len(specs) == 1
    spec = specs[0]
    assert set(spec.keys()) == {"name", "description", "input_schema"}
    assert spec["name"] == "foo"
    # No handler / destructive / permission leak into the tool spec.
    assert "handler" not in spec


def test_default_registry_has_default_commands():
    reg = build_default_registry()
    names = {c.name for c in reg.all()}
    assert names == {"award_dkp", "deduct_dkp", "bank_withdraw", "bank_deposit", "undo_last_command"}


def test_default_registry_destructive_flags():
    reg = build_default_registry()
    assert reg.get("award_dkp").destructive is False
    assert reg.get("deduct_dkp").destructive is True
    assert reg.get("bank_withdraw").destructive is True
    assert reg.get("bank_deposit").destructive is False
    assert reg.get("undo_last_command").destructive is True


def test_default_registry_schemas_are_strict_objects():
    reg = build_default_registry()
    for cmd in reg.all():
        schema = cmd.input_schema
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        assert "properties" in schema
        assert "required" in schema


def test_bank_deposit_category_enum():
    reg = build_default_registry()
    schema = reg.get("bank_deposit").input_schema
    enum = schema["properties"]["category"]["enum"]
    assert enum == [
        "ship_component",
        "commodities",
        "consumable",
        "equipment",
        "currency",
        "other",
    ]
