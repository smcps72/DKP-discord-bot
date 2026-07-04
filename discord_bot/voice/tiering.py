"""Entitlement and metering primitives for the voice platform.

Free tier = text-only (existing ``/ai`` command). Paid tier unlocks voice
features and TTS personas. This module is the deterministic, network-free
foundation that later voice phases gate on: tier resolution from a license
payload, voice-minute budgets, and usage-state computation (75%/100%
warnings). It deliberately imports nothing from discord/anthropic/network so
it stays trivially unit-testable.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# --- Open-beta gate ---------------------------------------------------------
# Voice AI commands are currently an OPEN BETA — free for everyone — while the
# feature is being tested. The paid-tier machinery below stays fully intact; it
# is simply not enforced until this switch is turned on. Set the env var
# VOICE_REQUIRE_PAID to a truthy value ("1"/"true"/"yes"/"on") to make voice
# premium (paid-tier only) again.
VOICE_REQUIRE_PAID_ENV = "VOICE_REQUIRE_PAID"


def voice_billing_enforced() -> bool:
    """Whether the paid-tier gate for voice is enforced.

    Defaults to ``False`` (open beta: voice free for all). Flip on later by
    setting ``VOICE_REQUIRE_PAID`` in the environment — no code change needed.
    """
    return os.environ.get(VOICE_REQUIRE_PAID_ENV, "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

# --- Tier constants ---------------------------------------------------------
FREE = "free"
PAID = "paid"
VALID_TIERS = {FREE, PAID}

# Monthly voice-minute budgets per tier. Free gets 0 (no voice at all); paid
# gets a flat 1000-minute monthly allowance.
VOICE_MINUTE_LIMITS = {FREE: 0, PAID: 1000}

# Usage thresholds (fractions of the limit) at which warnings fire.
WARN_THRESHOLD = 0.75
CAP_THRESHOLD = 1.0


def tier_from_license(data: dict) -> str:
    """Resolve an entitlement tier from a license-server payload.

    Returns :data:`PAID` only when the subscription is ``active`` *and* the
    payload's ``tier`` is a known paid tier. A lapsed/inactive subscription
    loses voice and is treated as :data:`FREE` regardless of its ``tier``.
    Missing/unknown tiers also fall back to :data:`FREE`.
    """
    if not isinstance(data, dict):
        return FREE
    # A subscription that is not active loses voice entitlements.
    if data.get("status") != "active":
        return FREE
    tier = data.get("tier")
    if tier in VALID_TIERS:
        return tier
    # An active subscription reporting a tier we don't recognize (e.g. a future
    # "premium"/"enterprise") is conservatively treated as free, but log it so a
    # silently-downgraded paying customer is visible rather than invisible.
    if tier is not None:
        logger.warning(
            "License reported unrecognized tier %r for an active subscription; "
            "defaulting to free. Add it to VALID_TIERS/VOICE_MINUTE_LIMITS if it "
            "should grant voice.",
            tier,
        )
    return FREE


def voice_allowed(tier: str) -> bool:
    """Return True only for tiers entitled to voice features."""
    return tier == PAID


def usage_state(used_minutes: float, limit_minutes: float) -> dict:
    """Compute the metering state for a guild's monthly voice usage.

    Returns a dict with ``used``, ``limit``, ``pct`` (0.0-..), ``level`` and
    ``remaining``. ``level`` is one of:

    - ``"ok"``     usage below 75% of the limit,
    - ``"warn"``   usage at/above 75% but below 100%,
    - ``"capped"`` usage at/above 100% of the limit.

    A zero limit (free tier) is treated as ``capped`` if any minutes were used,
    otherwise ``ok``. Division-by-zero is avoided.
    """
    used = float(used_minutes or 0)
    limit = float(limit_minutes or 0)

    if limit <= 0:
        # No budget: any usage is over the (zero) cap.
        level = "capped" if used > 0 else "ok"
        pct = 1.0 if used > 0 else 0.0
        return {
            "used": used,
            "limit": limit,
            "pct": pct,
            "level": level,
            "remaining": 0.0,
        }

    pct = used / limit
    if pct >= CAP_THRESHOLD:
        level = "capped"
    elif pct >= WARN_THRESHOLD:
        level = "warn"
    else:
        level = "ok"

    remaining = max(0.0, limit - used)
    return {
        "used": used,
        "limit": limit,
        "pct": pct,
        "level": level,
        "remaining": remaining,
    }


@dataclass
class Entitlements:
    """Resolved voice entitlements + metering state for a guild."""

    tier: str
    voice_allowed: bool
    minutes_used: float
    minutes_limit: float
    level: str
    remaining: float


async def load_entitlements(db, guild_id) -> Entitlements:
    """Load a guild's voice entitlements from the database.

    Reads ``get_guild_config`` and computes state via the pure helpers above.
    Tolerant of missing columns (older schemas): defaults to free tier with no
    minutes used.
    """
    cfg = await db.get_guild_config(guild_id)

    tier = FREE
    used = 0.0
    if cfg is not None:
        keys = cfg.keys()
        if "voice_tier" in keys and cfg["voice_tier"] in VALID_TIERS:
            tier = cfg["voice_tier"]
        if "voice_minutes_used" in keys and cfg["voice_minutes_used"] is not None:
            used = float(cfg["voice_minutes_used"])

    # Open beta: until billing is enforced, every guild is treated as paid for
    # entitlement purposes (voice free for all, full minute budget). The real
    # stored ``tier`` is still reported for display/future use.
    effective_tier = tier if voice_billing_enforced() else PAID
    limit = VOICE_MINUTE_LIMITS.get(effective_tier, 0)
    state = usage_state(used, limit)
    return Entitlements(
        tier=tier,
        voice_allowed=voice_allowed(effective_tier),
        minutes_used=state["used"],
        minutes_limit=state["limit"],
        level=state["level"],
        remaining=state["remaining"],
    )


async def reset_if_new_period(db, guild_id, current_period: str) -> bool:
    """Reset a guild's voice-minute meter when the billing period rolls over.

    ``current_period`` is an opaque period key (e.g. ``"2026-06"``). If the
    guild's stored ``voice_minutes_period`` differs, the meter and the 75%/100%
    warning flags are reset and the new period is recorded. Taking the period as
    a parameter (rather than reading a clock) keeps this deterministic and
    unit-testable. Returns True if a reset happened.

    Called opportunistically (e.g. on ``/voice start``) so a new month's quota is
    restored without a dedicated scheduler.
    """
    cfg = await db.get_guild_config(guild_id)
    stored = None
    if cfg is not None and "voice_minutes_period" in cfg.keys():
        stored = cfg["voice_minutes_period"]

    if stored == current_period:
        return False

    await db.reset_voice_minutes(guild_id)
    await db.execute(
        "UPDATE guilds SET voice_minutes_period = ? WHERE guild_id = ?",
        (current_period, guild_id),
    )
    return True
