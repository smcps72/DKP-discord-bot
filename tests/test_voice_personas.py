"""Offline tests for personas + speech guardrails.

Everything here is pure and deterministic: no discord / ElevenLabs / network.
Imports go through the full module path (the package __init__ does not re-export
these — the lead wires exports separately).
"""

import discord_bot.voice.personas as personas
from discord_bot.voice.personas import (
    DEFAULT_PERSONA_KEY,
    apply_persona,
    get_persona,
    list_personas,
    sanitize_for_speech,
    screen_text,
)


# --------------------------------------------------------------------------- #
# sanitize_for_speech
# --------------------------------------------------------------------------- #
def test_sanitize_strips_mass_pings():
    out = sanitize_for_speech("Hello @everyone and @here folks")
    assert "@everyone" not in out
    assert "@here" not in out
    assert "Hello" in out and "folks" in out


def test_sanitize_converts_mentions():
    out = sanitize_for_speech("ping <@123> and <@!456> in <#789> as <@&111>")
    assert "<@" not in out
    assert "<#" not in out
    assert "someone" in out
    assert "a channel" in out
    assert "a role" in out


def test_sanitize_collapses_urls():
    out = sanitize_for_speech("see https://example.com/path and www.foo.com now")
    assert "http" not in out
    assert "www." not in out
    assert out.count("a link") == 2


def test_sanitize_strips_control_chars():
    out = sanitize_for_speech("a\x00b\x07c\x1fd")
    assert "\x00" not in out and "\x07" not in out and "\x1f" not in out
    assert "abcd" in out.replace(" ", "")


def test_sanitize_caps_length_on_word_boundary():
    text = " ".join(["word"] * 300)  # 300 * 5 - 1 = 1499 chars
    out = sanitize_for_speech(text, max_chars=50)
    assert len(out) <= 53  # 50 + ellipsis allowance
    assert out.endswith("...")
    # Cut on a word boundary: no partial "wor" fragment at the tail.
    assert not out[:-3].rstrip().endswith("wor")


def test_sanitize_empty_returns_empty():
    assert sanitize_for_speech("") == ""
    assert sanitize_for_speech("   ") == ""


# --------------------------------------------------------------------------- #
# screen_text
# --------------------------------------------------------------------------- #
def test_screen_rejects_empty_and_whitespace():
    allowed, reason = screen_text("")
    assert allowed is False and reason
    allowed, reason = screen_text("   \n\t ")
    assert allowed is False and reason


def test_screen_allows_normal_text():
    allowed, reason = screen_text("Awarded 10 DKP to someone.")
    assert allowed is True
    assert reason is None


def test_screen_rejects_seeded_blocked_term(monkeypatch):
    monkeypatch.setattr(personas, "BLOCKED_TERMS", {"forbidden"})
    allowed, reason = screen_text("this contains a Forbidden word")
    assert allowed is False
    assert reason == "blocked content"
    # Unrelated text still allowed with the seed in place.
    assert screen_text("perfectly fine")[0] is True


# --------------------------------------------------------------------------- #
# get_persona / list_personas
# --------------------------------------------------------------------------- #
def test_get_persona_returns_default_for_unknown():
    assert get_persona("does-not-exist").key == DEFAULT_PERSONA_KEY
    assert get_persona(None).key == DEFAULT_PERSONA_KEY
    assert get_persona("").key == DEFAULT_PERSONA_KEY


def test_get_persona_returns_known():
    p = get_persona("herald")
    assert p.key == "herald"
    assert p.voice_id


def test_list_personas_includes_default():
    keys = {p.key for p in list_personas()}
    assert DEFAULT_PERSONA_KEY in keys
    assert len(keys) >= 3


# --------------------------------------------------------------------------- #
# apply_persona
# --------------------------------------------------------------------------- #
def test_apply_persona_is_deterministic_and_preserves_message():
    msg = "Awarded 10 DKP."
    herald = get_persona("herald")
    out1 = apply_persona(msg, herald)
    out2 = apply_persona(msg, herald)
    assert out1 == out2  # deterministic
    assert msg in out1  # core message preserved verbatim
    assert out1.startswith("Hear ye:")


def test_apply_persona_default_is_unframed():
    msg = "Awarded 10 DKP."
    out = apply_persona(msg, get_persona("default"))
    assert out == msg


def test_apply_persona_empty_returns_empty():
    assert apply_persona("", get_persona("herald")) == ""
