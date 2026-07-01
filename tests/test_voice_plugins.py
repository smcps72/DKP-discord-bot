"""Tests for the Phase 6 third-party programmable command interface."""

import pytest
from unittest.mock import MagicMock

from discord_bot.voice.registry import CommandRegistry, VoiceCommand
from discord_bot.voice.dispatch import Dispatcher, DispatchContext, DispatchResult
from discord_bot.voice.intent import IntentResult, NO_MATCH_TOOL_NAME
from discord_bot.voice.plugins import (
    ManifestError,
    RESERVED_COMMAND_NAMES,
    validate_command_manifest,
    build_command_from_manifest,
    register_manifest,
    discover_plugins,
)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _ctx():
    return DispatchContext(
        bot=MagicMock(),
        interaction=MagicMock(),
        guild_id=111,
        actor_id=222,
    )


def _good_entry(name="greet_member", **overrides):
    entry = {
        "name": name,
        "description": "Greet a guild member by name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "who": {"type": "string", "description": "Name to greet."},
            },
            "required": ["who"],
            "additionalProperties": False,
        },
    }
    entry.update(overrides)
    return entry


async def _ok_handler(args, ctx):
    return DispatchResult(status="ok", message=f"hi {args.get('who')}", data=dict(args))


# --------------------------------------------------------------------------- #
# validate_command_manifest
# --------------------------------------------------------------------------- #

def test_validate_good_entry():
    assert validate_command_manifest(_good_entry()) == []


def test_validate_missing_name():
    entry = _good_entry()
    del entry["name"]
    problems = validate_command_manifest(entry)
    assert problems and any("name" in p for p in problems)


def test_validate_missing_description():
    entry = _good_entry()
    del entry["description"]
    problems = validate_command_manifest(entry)
    assert problems and any("description" in p for p in problems)


def test_validate_missing_input_schema():
    entry = _good_entry()
    del entry["input_schema"]
    problems = validate_command_manifest(entry)
    assert problems and any("input_schema" in p for p in problems)


def test_validate_bad_name_chars():
    problems = validate_command_manifest(_good_entry(name="Greet-Member"))
    assert problems and any("snake_case" in p or "name" in p for p in problems)


def test_validate_reserved_name():
    problems = validate_command_manifest(_good_entry(name=NO_MATCH_TOOL_NAME))
    assert problems and any("reserved" in p for p in problems)


def test_validate_reserved_builtin_name():
    problems = validate_command_manifest(_good_entry(name="award_dkp"))
    assert problems and any("reserved" in p for p in problems)


def test_validate_bad_permission():
    problems = validate_command_manifest(_good_entry(permission="wizard"))
    assert problems and any("permission" in p for p in problems)


def test_validate_non_bool_destructive():
    problems = validate_command_manifest(_good_entry(destructive="yes"))
    assert problems and any("destructive" in p for p in problems)


def test_validate_schema_not_closed_object():
    # Missing additionalProperties + wrong type.
    entry = _good_entry()
    entry["input_schema"] = {"type": "array", "properties": {}}
    problems = validate_command_manifest(entry)
    assert problems and any("input_schema" in p for p in problems)


def test_validate_schema_missing_properties():
    entry = _good_entry()
    entry["input_schema"] = {"type": "object", "additionalProperties": False}
    problems = validate_command_manifest(entry)
    assert problems and any("properties" in p for p in problems)


def test_validate_schema_open_additional_properties_rejected():
    # additionalProperties: True is NOT a closed schema — the dispatcher only
    # rejects unknown args when it is exactly False, so this must be rejected.
    entry = _good_entry()
    entry["input_schema"] = {
        "type": "object",
        "properties": {"who": {"type": "string"}},
        "additionalProperties": True,
    }
    problems = validate_command_manifest(entry)
    assert problems and any("additionalProperties" in p for p in problems)


def test_reserved_names_includes_no_match_and_builtins():
    assert NO_MATCH_TOOL_NAME in RESERVED_COMMAND_NAMES
    assert "award_dkp" in RESERVED_COMMAND_NAMES


# --------------------------------------------------------------------------- #
# build_command_from_manifest
# --------------------------------------------------------------------------- #

def test_build_applies_defaults():
    cmd = build_command_from_manifest(_good_entry(), _ok_handler)
    assert isinstance(cmd, VoiceCommand)
    assert cmd.permission == "officer"
    assert cmd.destructive is False
    assert cmd.handler is _ok_handler


def test_build_raises_on_invalid():
    with pytest.raises(ManifestError):
        build_command_from_manifest(_good_entry(name="BAD NAME"), _ok_handler)


# --------------------------------------------------------------------------- #
# register_manifest
# --------------------------------------------------------------------------- #

def test_register_manifest_two_commands():
    reg = CommandRegistry()
    manifest = [_good_entry("alpha_cmd"), _good_entry("beta_cmd")]
    handlers = {"alpha_cmd": _ok_handler, "beta_cmd": _ok_handler}
    names = register_manifest(reg, manifest, handlers)
    assert names == ["alpha_cmd", "beta_cmd"]
    spec_names = {s["name"] for s in reg.tool_specs()}
    assert {"alpha_cmd", "beta_cmd"} <= spec_names


def test_register_manifest_commands_dict_form():
    reg = CommandRegistry()
    manifest = {"commands": [_good_entry("gamma_cmd")]}
    names = register_manifest(reg, manifest, {"gamma_cmd": _ok_handler})
    assert names == ["gamma_cmd"]


def test_register_manifest_missing_handler():
    reg = CommandRegistry()
    with pytest.raises(ManifestError):
        register_manifest(reg, [_good_entry("alpha_cmd")], {})


def test_register_manifest_collision_with_builtin():
    # award_dkp is reserved, so the manifest is rejected at validation time.
    reg = CommandRegistry()
    with pytest.raises(ManifestError):
        register_manifest(reg, [_good_entry("award_dkp")], {"award_dkp": _ok_handler})


def test_register_manifest_collision_with_existing():
    reg = CommandRegistry()
    register_manifest(reg, [_good_entry("alpha_cmd")], {"alpha_cmd": _ok_handler})
    with pytest.raises(ManifestError):
        register_manifest(reg, [_good_entry("alpha_cmd")], {"alpha_cmd": _ok_handler})


def test_register_manifest_namespace():
    reg = CommandRegistry()
    names = register_manifest(
        reg, [_good_entry("ping")], {"ping": _ok_handler}, namespace="acme"
    )
    assert names == ["acme_ping"]
    assert reg.get("acme_ping") is not None


def test_register_manifest_bad_namespace():
    reg = CommandRegistry()
    with pytest.raises(ManifestError):
        register_manifest(
            reg, [_good_entry("ping")], {"ping": _ok_handler}, namespace="Acme-Co"
        )


# --------------------------------------------------------------------------- #
# end-to-end dispatch
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_end_to_end_dispatch():
    reg = CommandRegistry()
    register_manifest(
        reg,
        [_good_entry("greet_member", permission="anyone")],
        {"greet_member": _ok_handler},
    )
    disp = Dispatcher(reg)
    result = await disp.dispatch(
        IntentResult(command_name="greet_member", args={"who": "Eskil"}),
        _ctx(),
    )
    assert result.status == "ok"
    assert result.data == {"who": "Eskil"}


# --------------------------------------------------------------------------- #
# discover_plugins
# --------------------------------------------------------------------------- #

_GOOD_PLUGIN = '''
from discord_bot.voice.registry import VoiceCommand
from discord_bot.voice.dispatch import DispatchResult


async def _handler(args, ctx):
    return DispatchResult(status="ok", message="plugged in")


def register(registry):
    registry.register(
        VoiceCommand(
            name="plugin_cmd",
            description="A command from a dropped-in plugin file.",
            input_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            handler=_handler,
            permission="anyone",
        )
    )
'''

_BROKEN_PLUGIN = "this is not valid python ::: import !!!\n"


def test_discover_plugins(tmp_path):
    (tmp_path / "good_plugin.py").write_text(_GOOD_PLUGIN)
    (tmp_path / "broken_plugin.py").write_text(_BROKEN_PLUGIN)
    # Skipped files: should not be imported / registered.
    (tmp_path / "_private.py").write_text("raise RuntimeError('should be skipped')")
    (tmp_path / "__init__.py").write_text("raise RuntimeError('should be skipped')")

    reg = CommandRegistry()
    added = discover_plugins(reg, str(tmp_path))

    assert added == ["plugin_cmd"]
    assert reg.get("plugin_cmd") is not None


def test_discover_plugins_missing_dir(tmp_path):
    reg = CommandRegistry()
    added = discover_plugins(reg, str(tmp_path / "does_not_exist"))
    assert added == []
