"""Command registry for the voice-controlled AI command platform.

The registry is the extensibility seam: commands are registered here, exposed
to the LLM as tool specs, validated server-side, permission-checked, and then
dispatched to a handler that reuses existing ``bot.db`` methods.  Third-party
apps register their own commands here later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


# A handler is an async callable: (args: dict, ctx) -> DispatchResult
Handler = Callable[[dict[str, Any], Any], Awaitable[Any]]

VALID_PERMISSIONS = {"admin", "officer", "raid_leader", "anyone"}


@dataclass
class VoiceCommand:
    """A single registered command the LLM can map an utterance to."""

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Handler
    destructive: bool = False
    permission: str = "officer"

    def __post_init__(self):
        if self.permission not in VALID_PERMISSIONS:
            raise ValueError(
                f"Invalid permission {self.permission!r} for command {self.name!r}; "
                f"expected one of {sorted(VALID_PERMISSIONS)}"
            )


class CommandRegistry:
    """Holds the set of commands available to the AI command platform."""

    def __init__(self):
        self._commands: dict[str, VoiceCommand] = {}

    def register(self, cmd: VoiceCommand) -> None:
        if cmd.name in self._commands:
            raise ValueError(f"Command {cmd.name!r} is already registered")
        self._commands[cmd.name] = cmd

    def get(self, name: str) -> VoiceCommand | None:
        return self._commands.get(name)

    def all(self) -> list[VoiceCommand]:
        return list(self._commands.values())

    def names(self) -> list[str]:
        """Return the names of every registered command (insertion order)."""
        return list(self._commands.keys())

    def tool_specs(self) -> list[dict[str, Any]]:
        """Return Anthropic tool specs for every registered command."""
        return [
            {
                "name": cmd.name,
                "description": cmd.description,
                "input_schema": cmd.input_schema,
            }
            for cmd in self._commands.values()
        ]


# JSON-Schema fragments reused across the default commands.

_CATEGORY_ENUM = [
    "ship_component",
    "commodities",
    "consumable",
    "equipment",
    "currency",
    "other",
]


def build_default_registry() -> CommandRegistry:
    """Wire up the four built-in commands (DKP + guild bank)."""
    # Imported here (not at module top) so the package import stays light and
    # the handlers module can import from registry without a cycle.
    from .handlers.dkp import award_dkp, deduct_dkp
    from .handlers.guild_bank import bank_deposit, bank_withdraw

    registry = CommandRegistry()

    registry.register(
        VoiceCommand(
            name="award_dkp",
            description=(
                "Grant DKP points to a member or to every member of the caller's "
                "active raid. Use when someone says to give, award, or add DKP."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": (
                            "A Discord mention like <@123> for a single member, "
                            "or 'all'/'everyone' for the whole active raid."
                        ),
                    },
                    "amount": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 1_000_000,
                        "description": "How many DKP points to award (1-1,000,000).",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Optional reason recorded with the award.",
                    },
                },
                "required": ["target", "amount"],
                "additionalProperties": False,
            },
            handler=award_dkp,
            destructive=False,
            permission="officer",
        )
    )

    registry.register(
        VoiceCommand(
            name="deduct_dkp",
            description=(
                "Remove DKP points from a member or from every member of the "
                "caller's active raid. Use when someone says to deduct, remove, "
                "subtract, or take away DKP."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": (
                            "A Discord mention like <@123> for a single member, "
                            "or 'all'/'everyone' for the whole active raid."
                        ),
                    },
                    "amount": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 1_000_000,
                        "description": "How many DKP points to deduct (1-1,000,000).",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Optional reason recorded with the deduction.",
                    },
                },
                "required": ["target", "amount"],
                "additionalProperties": False,
            },
            handler=deduct_dkp,
            destructive=True,
            permission="officer",
        )
    )

    registry.register(
        VoiceCommand(
            name="bank_withdraw",
            description=(
                "Withdraw a quantity of an item from the guild bank by item name. "
                "Use when someone says to withdraw, take out, or remove an item "
                "from the bank."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "item_name": {
                        "type": "string",
                        "description": "The name of the guild bank item to withdraw.",
                    },
                    "quantity": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 100_000,
                        "description": "How many to withdraw (1-100,000).",
                    },
                },
                "required": ["item_name", "quantity"],
                "additionalProperties": False,
            },
            handler=bank_withdraw,
            destructive=True,
            permission="officer",
        )
    )

    registry.register(
        VoiceCommand(
            name="bank_deposit",
            description=(
                "Deposit a quantity of an item into the guild bank. Use when "
                "someone says to deposit, add, or put an item into the bank."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "item_name": {
                        "type": "string",
                        "description": "The name of the item to deposit.",
                    },
                    "quantity": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 100_000,
                        "description": "How many to deposit (1-100,000).",
                    },
                    "category": {
                        "type": "string",
                        "enum": _CATEGORY_ENUM,
                        "description": "Item category. Defaults to 'other'.",
                    },
                    "location": {
                        "type": "string",
                        "description": "Optional storage location note.",
                    },
                    "held_by_user_id": {
                        "type": "integer",
                        "description": (
                            "Optional Discord user id holding the item. "
                            "Defaults to the caller."
                        ),
                    },
                },
                "required": ["item_name", "quantity"],
                "additionalProperties": False,
            },
            handler=bank_deposit,
            destructive=False,
            permission="officer",
        )
    )

    return registry
