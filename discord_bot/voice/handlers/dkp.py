"""DKP handlers for the voice AI command platform.

Reuse ``bot.db.modify_user_dkp`` (and the raid-roster helpers for "all"/"everyone").
"""

from __future__ import annotations

import re
from typing import Any

from ..dispatch import DispatchContext, DispatchResult


_MENTION_RE = re.compile(r"<@!?(\d+)>")
_ALL_TOKENS = {"all", "everyone"}


def _resolve_target_id(target: str) -> int | None:
    """Resolve a ``<@id>`` mention (or bare digits) to an int user id."""
    if target is None:
        return None
    target = str(target).strip()
    match = _MENTION_RE.fullmatch(target)
    if match:
        return int(match.group(1))
    if target.isdigit():
        return int(target)
    return None


async def _raid_member_ids(ctx: DispatchContext) -> list[int] | None:
    """Return member ids of the caller's active raid, or None if no active raid."""
    raid = await ctx.bot.db.get_active_raid_by_leader(ctx.guild_id, ctx.actor_id)
    if not raid:
        return None
    raid_id = raid["id"]
    rows = await ctx.bot.db.get_raid_members(raid_id)
    ids: list[int] = []
    for row in rows or []:
        try:
            ids.append(int(row["user_id"]))
        except Exception:
            continue
    return ids


async def _apply(ctx: DispatchContext, args: dict[str, Any], sign: int, verb: str) -> DispatchResult:
    target = str(args.get("target", "")).strip()
    amount = int(args["amount"])
    reason = (args.get("reason") or f"voice/ai {verb}").strip()
    delta = sign * amount

    if target.lower() in _ALL_TOKENS:
        member_ids = await _raid_member_ids(ctx)
        if member_ids is None:
            return DispatchResult(
                status="error",
                message=(
                    "You're not leading an active raid, so there's no roster to apply "
                    "DKP to. ('all'/'everyone' targets the raid you lead."
                ),
            )
        if not member_ids:
            return DispatchResult(
                status="error",
                message="Your active raid has no members yet.",
            )
        for user_id in member_ids:
            await ctx.bot.db.modify_user_dkp(user_id, ctx.guild_id, delta, reason)
        return DispatchResult(
            status="ok",
            message=f"{verb.capitalize()}ed {amount} DKP {('to' if sign > 0 else 'from')} {len(member_ids)} raid member(s).",
            data={"count": len(member_ids), "amount": amount, "sign": sign},
        )

    user_id = _resolve_target_id(target)
    if user_id is None:
        return DispatchResult(
            status="error",
            message=f"Couldn't understand the target '{target}'. Use a mention or 'all'.",
        )
    await ctx.bot.db.modify_user_dkp(user_id, ctx.guild_id, delta, reason)
    return DispatchResult(
        status="ok",
        message=f"{verb.capitalize()}ed {amount} DKP {('to' if sign > 0 else 'from')} <@{user_id}>.",
        data={"user_id": user_id, "amount": amount, "sign": sign},
    )


async def award_dkp(args: dict[str, Any], ctx: DispatchContext) -> DispatchResult:
    return await _apply(ctx, args, sign=1, verb="award")


async def deduct_dkp(args: dict[str, Any], ctx: DispatchContext) -> DispatchResult:
    return await _apply(ctx, args, sign=-1, verb="deduct")
