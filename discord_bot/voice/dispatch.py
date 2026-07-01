"""Dispatcher: resolve an intent to a command, re-validate, permission-check,
gate destructive actions behind confirmation, and run the handler.

The LLM (in strict mode) only guarantees the *shape* of the arguments, so the
dispatcher re-validates them server-side against the command's JSON Schema
before doing anything irreversible.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from .intent import IntentResult
from .registry import CommandRegistry, VoiceCommand


@dataclass
class DispatchContext:
    """Everything a handler needs to act, independent of the discord cog."""

    bot: Any
    interaction: Any
    guild_id: int
    actor_id: int


@dataclass
class DispatchResult:
    """The outcome of a dispatch attempt.

    ``status`` is one of: ok, error, needs_confirmation, unknown_command,
    denied, invalid_args.
    """

    status: str
    message: str
    confirm_summary: str | None = None
    data: dict[str, Any] | None = None


def _validate_args(schema: dict[str, Any], args: dict[str, Any]) -> str | None:
    """Validate ``args`` against a (subset of) JSON Schema.

    Returns ``None`` if valid, otherwise a human-readable error message.
    """
    properties: dict[str, Any] = schema.get("properties", {})
    required: list[str] = schema.get("required", [])

    if schema.get("additionalProperties") is False:
        extra = [k for k in args if k not in properties]
        if extra:
            return f"Unexpected argument(s): {', '.join(sorted(extra))}."

    for key in required:
        if key not in args or args[key] is None:
            return f"Missing required argument '{key}'."

    for key, value in args.items():
        spec = properties.get(key)
        if spec is None:
            continue
        expected = spec.get("type")
        if expected == "integer":
            # bool is a subclass of int — reject it explicitly.
            if isinstance(value, bool) or not isinstance(value, int):
                return f"Argument '{key}' must be an integer."
        elif expected == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return f"Argument '{key}' must be a number."
        elif expected == "string":
            if not isinstance(value, str):
                return f"Argument '{key}' must be a string."
        elif expected == "boolean":
            if not isinstance(value, bool):
                return f"Argument '{key}' must be a boolean."

        if "enum" in spec and value not in spec["enum"]:
            allowed = ", ".join(str(v) for v in spec["enum"])
            return f"Argument '{key}' must be one of: {allowed}."

        if expected in ("integer", "number") and not isinstance(value, bool):
            if "minimum" in spec and value < spec["minimum"]:
                return f"Argument '{key}' must be >= {spec['minimum']}."
            if "maximum" in spec and value > spec["maximum"]:
                return f"Argument '{key}' must be <= {spec['maximum']}."

    return None


async def _check_permission(command: VoiceCommand, ctx: DispatchContext) -> bool:
    """Return True if the actor may run ``command``."""
    perm = command.permission
    if perm == "anyone":
        return True

    # Imported lazily so the package import doesn't pull in discord/utils.
    from ..utils import is_admin, is_officer, is_raid_leader

    interaction = ctx.interaction
    if perm == "admin":
        return await is_admin(interaction)
    if perm == "officer":
        return await is_officer(interaction)
    if perm == "raid_leader":
        return await is_raid_leader(interaction)
    return False


class Dispatcher:
    """Runs an :class:`IntentResult` through the validate/permission/confirm/run
    pipeline against a :class:`CommandRegistry`."""

    def __init__(self, registry: CommandRegistry):
        self.registry = registry

    async def dispatch(
        self,
        intent: IntentResult,
        ctx: DispatchContext,
        confirmed: bool = False,
    ) -> DispatchResult:
        # 1. Resolve the command.
        if not intent.command_name:
            return DispatchResult(
                status="unknown_command",
                message="I couldn't match that to a known command.",
            )
        command = self.registry.get(intent.command_name)
        if command is None:
            return DispatchResult(
                status="unknown_command",
                message=f"Unknown command '{intent.command_name}'.",
            )

        # 2. Re-validate args server-side.
        error = _validate_args(command.input_schema, intent.args or {})
        if error:
            return DispatchResult(status="invalid_args", message=error)

        # 3. Permission check.
        try:
            allowed = await _check_permission(command, ctx)
        except Exception:
            logging.exception("Permission check failed for %s", command.name)
            allowed = False
        if not allowed:
            return DispatchResult(
                status="denied",
                message=(
                    f"You don't have permission to use '{command.name}' "
                    f"(requires {command.permission})."
                ),
            )

        # 4. Confirmation gate for destructive commands.
        if command.destructive and not confirmed:
            return DispatchResult(
                status="needs_confirmation",
                message="This action needs confirmation.",
                confirm_summary=self._confirm_summary(command, intent.args or {}),
            )

        # 5. Run the handler.
        try:
            result = await command.handler(intent.args or {}, ctx)
        except Exception as exc:
            logging.exception("Handler for %s raised", command.name)
            return DispatchResult(
                status="error",
                message=f"The command failed: {exc}",
            )

        if result.status == "ok" and isinstance(result.data, dict):
            undo = result.data.get("undo")
            if isinstance(undo, dict):
                action = undo.get("action")
                data = undo.get("data") if isinstance(undo.get("data"), dict) else {}
                if action:
                    try:
                        entry_id = await ctx.bot.db.record_command_undo(
                            ctx.guild_id,
                            ctx.actor_id,
                            command.name,
                            intent.args or {},
                            str(action),
                            data,
                        )
                        result.data["undo_entry_id"] = entry_id
                    except Exception:
                        logging.exception("Failed to record undo entry for %s", command.name)
        return result

    @staticmethod
    def _confirm_summary(command: VoiceCommand, args: dict[str, Any]) -> str:
        arg_text = ", ".join(f"{k}={v!r}" for k, v in args.items())
        return f"Run '{command.name}' with {arg_text}?" if arg_text else f"Run '{command.name}'?"
