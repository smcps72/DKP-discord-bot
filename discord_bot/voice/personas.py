"""Personas + speech guardrails for the TTS speak-back feature (paid tier).

A *persona* is a selectable voice + style for the bot's spoken replies. This
module is the deterministic, network-free policy layer that sits in front of any
text-to-speech synthesis:

* :data:`PERSONAS` is the built-in catalogue (an ElevenLabs ``voice_id`` plus a
  short, PG, non-impersonating flavour ``style``).
* :func:`sanitize_for_speech` neutralises anything unsafe/awkward to read aloud
  (mass pings, raw mentions, URLs, control chars) and caps length.
* :func:`screen_text` is the content-safety gate (the documented moderation
  policy hook) — synthesis MUST call it and refuse when it returns not-allowed.
* :func:`apply_persona` lightly frames the (already-sanitised) text per persona
  *without* changing the factual content.

Import-time contract
--------------------
This module imports nothing from discord / ElevenLabs / network. It is pure and
trivially unit-testable. TTS synthesis and Discord playback live in
:mod:`discord_bot.voice.tts`; this module only decides *what text is spoken*.

Legal note
----------
Speak-back was legally flagged in the brainstorm: persona styles must stay PG
and must not impersonate real, identifiable people, and all text must pass
:func:`screen_text` before synthesis. The guardrails here are therefore
mandatory, not optional.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "Persona",
    "PERSONAS",
    "DEFAULT_PERSONA_KEY",
    "get_persona",
    "list_personas",
    "sanitize_for_speech",
    "screen_text",
    "apply_persona",
    "BLOCKED_TERMS",
]


@dataclass(frozen=True)
class Persona:
    """A selectable spoken voice + style.

    Attributes
    ----------
    key:
        Stable lookup key persisted in the guild config (e.g. ``"herald"``).
    display_name:
        Human-friendly name shown in command embeds.
    voice_id:
        An ElevenLabs voice id. Placeholder ids are used here; swap them for
        real ones from your ElevenLabs account without touching any other code.
    style:
        A short, PG, non-impersonating flavour descriptor. Drives the light
        framing in :func:`apply_persona`; it never rewrites factual content.
    """

    key: str
    display_name: str
    voice_id: str
    style: str


# Built-in persona catalogue. ``voice_id`` values are placeholders — replace
# with real ElevenLabs voice ids. Styles are intentionally PG and generic (no
# impersonation of real, identifiable people).
PERSONAS: dict[str, "Persona"] = {
    "default": Persona(
        key="default",
        display_name="Default",
        voice_id="elevenlabs-voice-default",
        style="neutral",
    ),
    "herald": Persona(
        key="herald",
        display_name="Herald",
        voice_id="elevenlabs-voice-herald",
        style="formal announcer",
    ),
    "drill_sergeant": Persona(
        key="drill_sergeant",
        display_name="Drill Sergeant",
        voice_id="elevenlabs-voice-drill",
        style="brisk and commanding",
    ),
    "sage": Persona(
        key="sage",
        display_name="Sage",
        voice_id="elevenlabs-voice-sage",
        style="calm and measured",
    ),
}

DEFAULT_PERSONA_KEY = "default"


def get_persona(key: str) -> "Persona":
    """Return the :class:`Persona` for ``key``, or the default if unknown.

    Tolerant of ``None``/unknown keys so callers can pass a possibly-missing
    guild config value directly.
    """
    if not key:
        return PERSONAS[DEFAULT_PERSONA_KEY]
    return PERSONAS.get(key, PERSONAS[DEFAULT_PERSONA_KEY])


def list_personas() -> list["Persona"]:
    """Return all built-in personas (default first, then insertion order)."""
    return list(PERSONAS.values())


# --------------------------------------------------------------------------- #
# Guardrails
# --------------------------------------------------------------------------- #

# Content-safety blocklist — the documented policy extension point. Seed it with
# terms (lower-cased) that must never be synthesized; left mostly empty by design
# so operators can extend moderation policy without code changes elsewhere.
BLOCKED_TERMS: set[str] = set()

# Mass-ping tokens that must never be spoken/echoed.
_MASS_PING_RE = re.compile(r"@everyone|@here", re.IGNORECASE)
# User mentions: <@123> and <@!123>.
_USER_MENTION_RE = re.compile(r"<@!?\d+>")
# Channel mentions: <#123>.
_CHANNEL_MENTION_RE = re.compile(r"<#\d+>")
# Role mentions: <@&123>.
_ROLE_MENTION_RE = re.compile(r"<@&\d+>")
# URLs of common schemes, collapsed to "a link".
_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
# Control characters (except common whitespace handled separately).
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# Runs of whitespace collapse to a single space.
_WS_RE = re.compile(r"\s+")


def sanitize_for_speech(text: str, *, max_chars: int = 600) -> str:
    """Neutralise anything unsafe or awkward to read aloud and cap length.

    Steps (order matters):

    1. Strip control characters.
    2. Remove ``@everyone`` / ``@here`` mass pings entirely.
    3. Replace role mentions (``<@&..>``) with "a role", channel mentions
       (``<#..>``) with "a channel", and user mentions (``<@..>`` / ``<@!..>``)
       with "someone".
    4. Collapse URLs to "a link".
    5. Collapse whitespace runs to single spaces and trim.
    6. Cap to ``max_chars`` on a word boundary, appending an ellipsis when cut.

    Returns the cleaned string (possibly empty if the input was all noise).
    """
    if not text:
        return ""

    cleaned = _CONTROL_RE.sub("", text)
    cleaned = _MASS_PING_RE.sub("", cleaned)
    # Role/channel before the generic user mention (which would otherwise eat
    # the leading "<@" of a role mention).
    cleaned = _ROLE_MENTION_RE.sub("a role", cleaned)
    cleaned = _CHANNEL_MENTION_RE.sub("a channel", cleaned)
    cleaned = _USER_MENTION_RE.sub("someone", cleaned)
    cleaned = _URL_RE.sub("a link", cleaned)
    cleaned = _WS_RE.sub(" ", cleaned).strip()

    if len(cleaned) <= max_chars:
        return cleaned

    # Cut on a word boundary within the budget, then add an ellipsis.
    head = cleaned[:max_chars]
    if " " in head:
        head = head[: head.rfind(" ")]
    head = head.rstrip()
    return f"{head}..." if head else cleaned[:max_chars].rstrip() + "..."


def screen_text(text: str) -> tuple[bool, "str | None"]:
    """Content-safety gate. Returns ``(allowed, reason)``.

    This is the moderation policy hook the synthesis path MUST consult before
    speaking anything. It currently enforces two rules and is built to be
    extended:

    * Reject empty/whitespace-only text (nothing to speak).
    * Reject text containing any term in :data:`BLOCKED_TERMS` (case-insensitive,
      substring match) — seed that set to expand policy without touching callers.

    ``reason`` is ``None`` when allowed, otherwise a short human-readable cause.
    """
    if not text or not text.strip():
        return False, "empty text"

    lowered = text.lower()
    for term in BLOCKED_TERMS:
        if term and term.lower() in lowered:
            return False, "blocked content"

    return True, None


def apply_persona(text: str, persona: "Persona") -> str:
    """Lightly frame ``text`` for ``persona`` WITHOUT changing factual content.

    Deterministic and minimal: this only adds a small flavour prefix per style;
    it never rewrites, summarises, or reorders the underlying message. The core
    message is always preserved verbatim as a substring of the result.
    """
    body = (text or "").strip()
    if not body:
        return body

    prefix = _PERSONA_PREFIX.get(persona.key, "")
    return f"{prefix}{body}" if prefix else body


# Deterministic, minimal per-persona flavour prefixes. Kept here (not on the
# dataclass) so the persona catalogue stays pure data.
_PERSONA_PREFIX: dict[str, str] = {
    "herald": "Hear ye: ",
    "drill_sergeant": "Listen up: ",
    "sage": "Mark my words: ",
}
