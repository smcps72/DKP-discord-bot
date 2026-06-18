"""Intent parsing: turn a transcript into a single registered command + args.

``IntentParser`` is the abstraction.  ``ClaudeIntentParser`` uses the Anthropic
Messages API with strict tool use to map an utterance onto exactly one
registered command.  ``ScriptedIntentParser`` is a deterministic, network-free
implementation used by tests.
"""

from __future__ import annotations

import abc
import os
from dataclasses import dataclass, field
from typing import Any

from .registry import CommandRegistry


DEFAULT_MODEL = "claude-haiku-4-5"

SYSTEM_PROMPT = (
    "You translate a guild member's natural-language request into exactly one "
    "of the provided commands. Only map the request to a command that is listed "
    "as an available tool. If the request does not clearly correspond to one of "
    "the listed commands, decline by not calling any tool. Never invent commands "
    "or arguments that are not in the tool schemas."
)


@dataclass
class IntentResult:
    """The outcome of parsing a transcript.

    ``command_name`` is None when no confident command match was found.
    """

    command_name: str | None
    args: dict[str, Any] = field(default_factory=dict)
    raw: str = ""


class IntentParser(abc.ABC):
    """Abstract base for transcript -> intent mappers."""

    @abc.abstractmethod
    async def parse(self, transcript: str, registry: CommandRegistry) -> IntentResult:
        raise NotImplementedError


class ClaudeIntentParser(IntentParser):
    """Maps an utterance to a registered command via the Anthropic API.

    The ``anthropic`` package is imported lazily inside ``parse`` so importing
    this module is side-effect-free and network-free.
    """

    def __init__(self, *, model: str | None = None, api_key: str | None = None):
        self.model = model or os.environ.get("VOICE_LLM_MODEL", DEFAULT_MODEL)
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")

    async def parse(self, transcript: str, registry: CommandRegistry) -> IntentResult:
        import anthropic  # lazy import — no network/dep at module import time

        client = anthropic.AsyncAnthropic(api_key=self.api_key)
        tools = registry.tool_specs()

        message = await client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=tools,
            tool_choice={"type": "any", "disable_parallel_tool_use": True},
            messages=[{"role": "user", "content": transcript}],
        )

        for block in message.content:
            if getattr(block, "type", None) == "tool_use":
                args = block.input if isinstance(block.input, dict) else {}
                return IntentResult(
                    command_name=block.name,
                    args=dict(args),
                    raw=transcript,
                )

        return IntentResult(command_name=None, args={}, raw=transcript)


class ScriptedIntentParser(IntentParser):
    """Deterministic parser for tests — no network.

    Constructed with ``rules``: a list of ``(substring, (command_name, args))``.
    The first rule whose substring appears (case-insensitive) in the transcript
    wins. If nothing matches, returns a no-match IntentResult.
    """

    def __init__(self, rules: list[tuple[str, tuple[str, dict[str, Any]]]] | None = None):
        self.rules = list(rules or [])

    async def parse(self, transcript: str, registry: CommandRegistry) -> IntentResult:
        lowered = (transcript or "").lower()
        for substring, (command_name, args) in self.rules:
            if substring.lower() in lowered:
                return IntentResult(
                    command_name=command_name,
                    args=dict(args),
                    raw=transcript,
                )
        return IntentResult(command_name=None, args={}, raw=transcript)
