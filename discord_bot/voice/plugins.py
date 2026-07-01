"""Programmable third-party command interface for the voice AI platform.

Phase 6 lets a *trusted host application* extend the command platform without
editing core code, while keeping a clear security boundary:

* **Metadata is declarative and validated.** A command *manifest* is plain data
  (name, description, JSON-Schema for arguments, permission, destructive flag).
  It is validated thoroughly here before anything is registered — it is treated
  as untrusted input.
* **Executable handlers stay with the host.** The async callables that actually
  run a command are supplied by the host application (a ``handlers`` map, or a
  plugin module's own ``register`` function). Handlers are *never* deserialized
  from the manifest, so dropping a manifest file can never inject code.

Three entry points:

``validate_command_manifest`` / ``build_command_from_manifest``
    Validate one manifest entry and turn it (plus a host handler) into a
    :class:`~discord_bot.voice.registry.VoiceCommand`.
``register_manifest``
    Validate + register a whole manifest (list or ``{"commands": [...]}``) into
    a registry, binding each entry to a host-supplied handler, with optional
    namespacing.
``discover_plugins``
    Import ``*.py`` plugin files from a directory and call their ``register``
    hook, isolating failures so one bad plugin can't abort discovery.

The module is import-clean: no discord/anthropic/network at import time.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import re
from typing import Any, Awaitable, Callable

from .intent import NO_MATCH_TOOL_NAME
from .registry import VALID_PERMISSIONS, CommandRegistry, VoiceCommand

logger = logging.getLogger(__name__)

# snake_case identifier used for command names and namespaces.
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")

# Anthropic tool names must match this; notably no dots are allowed, which is
# why namespacing uses an underscore-join rather than a dotted prefix.
_TOOL_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

# The built-in command names. Hardcoded (rather than derived via
# ``build_default_registry``) so this module stays import-clean — importing the
# real registry would pull in the handler modules and their db dependencies.
_BUILTIN_COMMAND_NAMES = (
    "award_dkp",
    "deduct_dkp",
    "bank_withdraw",
    "bank_deposit",
)

#: Names a third-party manifest may never register: the decline pseudo-tool and
#: the built-in commands.
RESERVED_COMMAND_NAMES: frozenset[str] = frozenset(
    {NO_MATCH_TOOL_NAME, *_BUILTIN_COMMAND_NAMES}
)


class ManifestError(Exception):
    """Raised when a command manifest is invalid or cannot be registered."""


def validate_command_manifest(entry: dict) -> list[str]:
    """Validate ONE command manifest entry.

    Returns a list of human-readable problems; an empty list means the entry is
    valid. This is the trust boundary for untrusted command metadata, so it is
    deliberately strict and exhaustive.
    """
    problems: list[str] = []

    if not isinstance(entry, dict):
        return [f"Manifest entry must be a dict, got {type(entry).__name__}."]

    # --- name -------------------------------------------------------------
    if "name" not in entry:
        problems.append("Missing required key 'name'.")
    else:
        name = entry["name"]
        if not isinstance(name, str) or not name:
            problems.append("'name' must be a non-empty string.")
        elif not _NAME_RE.match(name):
            problems.append(
                f"'name' {name!r} must be snake_case matching ^[a-z][a-z0-9_]*$."
            )
        elif name in RESERVED_COMMAND_NAMES:
            problems.append(f"'name' {name!r} is reserved and cannot be used.")

    # --- description ------------------------------------------------------
    if "description" not in entry:
        problems.append("Missing required key 'description'.")
    else:
        description = entry["description"]
        if not isinstance(description, str) or not description.strip():
            problems.append("'description' must be a non-empty string.")

    # --- input_schema -----------------------------------------------------
    if "input_schema" not in entry:
        problems.append("Missing required key 'input_schema'.")
    else:
        problems.extend(_validate_input_schema(entry["input_schema"]))

    # --- permission (optional) -------------------------------------------
    if "permission" in entry:
        permission = entry["permission"]
        if permission not in VALID_PERMISSIONS:
            problems.append(
                f"'permission' {permission!r} must be one of "
                f"{sorted(VALID_PERMISSIONS)}."
            )

    # --- destructive (optional) ------------------------------------------
    if "destructive" in entry and not isinstance(entry["destructive"], bool):
        problems.append("'destructive' must be a boolean.")

    return problems


def _validate_input_schema(schema: Any) -> list[str]:
    """Validate that ``schema`` is a well-formed closed object JSON Schema."""
    problems: list[str] = []
    if not isinstance(schema, dict):
        return ["'input_schema' must be a dict."]

    if schema.get("type") != "object":
        problems.append("'input_schema' must have \"type\": \"object\".")

    properties = schema.get("properties")
    if not isinstance(properties, dict):
        problems.append("'input_schema' must have a 'properties' dict.")

    if "additionalProperties" not in schema:
        problems.append(
            "'input_schema' must set 'additionalProperties' to be a closed "
            "object schema."
        )
    elif schema["additionalProperties"] is not False:
        # A closed schema is the trust guarantee: the dispatcher only rejects
        # unknown args when additionalProperties is exactly False, so anything
        # else (True / a sub-schema) would let unvalidated arguments through.
        problems.append(
            "'input_schema' must set 'additionalProperties': false (a closed "
            "object schema); other values allow unvalidated arguments."
        )

    return problems


def build_command_from_manifest(entry: dict, handler: Callable[..., Awaitable[Any]]) -> VoiceCommand:
    """Build a :class:`VoiceCommand` from a manifest ``entry`` + host ``handler``.

    Raises :class:`ManifestError` listing every problem if the entry is invalid.
    Defaults are applied for the optional fields (permission ``"officer"``,
    destructive ``False``).
    """
    problems = validate_command_manifest(entry)
    if problems:
        raise ManifestError(
            "Invalid command manifest entry: " + "; ".join(problems)
        )
    if not callable(handler):
        raise ManifestError(
            f"Handler for command {entry.get('name')!r} must be callable."
        )

    return VoiceCommand(
        name=entry["name"],
        description=entry["description"],
        input_schema=entry["input_schema"],
        handler=handler,
        destructive=bool(entry.get("destructive", False)),
        permission=entry.get("permission", "officer"),
    )


def _manifest_entries(manifest: dict | list) -> list[dict]:
    """Normalise a manifest into a list of entries."""
    if isinstance(manifest, list):
        return manifest
    if isinstance(manifest, dict):
        commands = manifest.get("commands")
        if not isinstance(commands, list):
            raise ManifestError(
                "Manifest dict must contain a 'commands' list."
            )
        return commands
    raise ManifestError(
        "Manifest must be a list of entries or a dict with a 'commands' list."
    )


def register_manifest(
    registry: CommandRegistry,
    manifest: dict | list,
    handlers: dict[str, Callable[..., Awaitable[Any]]],
    *,
    namespace: str | None = None,
) -> list[str]:
    """Validate and register every command in ``manifest`` into ``registry``.

    ``handlers`` maps a manifest entry's *declared* name (before namespacing) to
    the host-supplied async callable. If ``namespace`` is given, each registered
    command name becomes ``f"{namespace}_{name}"`` (underscore-join, because
    Anthropic tool names disallow dots).

    Returns the list of final registered names. Raises :class:`ManifestError`
    for a missing handler, an invalid entry, an invalid namespace, a resulting
    name that breaks the tool-name rules, or a collision with an
    already-registered command.
    """
    if namespace is not None:
        if not isinstance(namespace, str) or not _NAME_RE.match(namespace):
            raise ManifestError(
                f"namespace {namespace!r} must be snake_case matching "
                "^[a-z][a-z0-9_]*$."
            )

    entries = _manifest_entries(manifest)

    # Validate everything and build commands BEFORE mutating the registry, so a
    # failure half-way through doesn't leave a partially-registered manifest.
    built: list[VoiceCommand] = []
    seen: set[str] = set()
    for entry in entries:
        problems = validate_command_manifest(entry)
        if problems:
            raise ManifestError(
                "Invalid command manifest entry: " + "; ".join(problems)
            )

        declared_name = entry["name"]
        handler = handlers.get(declared_name)
        if handler is None:
            raise ManifestError(
                f"No handler supplied for command {declared_name!r}."
            )

        final_name = f"{namespace}_{declared_name}" if namespace else declared_name
        if not _TOOL_NAME_RE.match(final_name):
            raise ManifestError(
                f"Registered name {final_name!r} must match "
                "^[a-zA-Z0-9_-]{1,64}$ (Anthropic tool-name rule)."
            )
        if final_name in RESERVED_COMMAND_NAMES:
            raise ManifestError(
                f"Registered name {final_name!r} is reserved."
            )
        if final_name in seen:
            raise ManifestError(
                f"Duplicate command name {final_name!r} within manifest."
            )
        if registry.get(final_name) is not None:
            raise ManifestError(
                f"Command {final_name!r} collides with an already-registered "
                "command."
            )
        seen.add(final_name)

        # Build with the final (possibly namespaced) name.
        cmd = build_command_from_manifest({**entry, "name": final_name}, handler)
        built.append(cmd)

    registered: list[str] = []
    for cmd in built:
        try:
            registry.register(cmd)
        except ValueError as exc:  # defensive — collisions were pre-checked
            raise ManifestError(str(exc)) from exc
        registered.append(cmd.name)

    return registered


def discover_plugins(registry: CommandRegistry, directory: str) -> list[str]:
    """Import every plugin module in ``directory`` and run its ``register`` hook.

    A plugin is a top-level ``*.py`` file (not recursive; ``__init__.py`` and
    files starting with ``_`` are skipped) that defines a callable
    ``register(registry)``. The plugin module supplies its own handlers (real
    code), consistent with the trust model — only *data* manifests are treated
    as untrusted.

    Import or registration failures in one plugin are logged and skipped so a
    single bad file can't abort the whole discovery. Returns the names of the
    commands that were actually added to ``registry``.
    """
    added: list[str] = []
    if not os.path.isdir(directory):
        logger.warning("Plugin directory %r does not exist; skipping.", directory)
        return added

    before = set(registry.names())

    for filename in sorted(os.listdir(directory)):
        if not filename.endswith(".py"):
            continue
        if filename == "__init__.py" or filename.startswith("_"):
            continue

        path = os.path.join(directory, filename)
        module_name = f"_voice_plugin_{os.path.splitext(filename)[0]}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, path)
            if spec is None or spec.loader is None:
                logger.warning("Could not create import spec for plugin %r.", path)
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception:
            logger.exception("Failed to import plugin %r; skipping.", path)
            continue

        register = getattr(module, "register", None)
        if not callable(register):
            logger.debug("Plugin %r has no callable register(); skipping.", path)
            continue

        snapshot = set(registry.names())
        try:
            register(registry)
        except Exception:
            # A plugin may have registered some commands before raising; record
            # whatever it actually added so the return value is truthful.
            logger.exception(
                "Plugin %r register() failed; any partial registration is kept.",
                path,
            )
        finally:
            added.extend(n for n in registry.names() if n not in snapshot)

    # Preserve registration order while deduping against pre-existing names.
    return [n for n in added if n not in before]
