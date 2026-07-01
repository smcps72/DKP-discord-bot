"""DKP handlers for the voice AI command platform.

Reuse ``bot.db.modify_user_dkp`` (and the raid-roster helpers for "all"/"everyone").
"""

from __future__ import annotations

import inspect
import logging
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


def _row_get(row: Any, key: str, default: Any = None) -> Any:
    try:
        return row[key]
    except Exception:
        return getattr(row, key, default)


async def _active_raid_roster(ctx: DispatchContext) -> tuple[Any | None, list[int] | None]:
    raid = await ctx.bot.db.get_active_raid_by_leader(ctx.guild_id, ctx.actor_id)
    if not raid:
        return None, None
    raid_id = _row_get(raid, "id")
    rows = await ctx.bot.db.get_raid_members(raid_id)
    ids: list[int] = []
    for row in rows or []:
        try:
            ids.append(int(row["user_id"]))
        except Exception:
            continue
    return raid, ids


def _actor_mention(ctx: DispatchContext) -> str:
    user = getattr(getattr(ctx, "interaction", None), "user", None)
    mention = getattr(user, "mention", None)
    if isinstance(mention, str) and mention:
        return mention
    return f"<@{int(ctx.actor_id)}>"


async def _send_to_candidate(candidate: Any, message: str) -> bool:
    if candidate is None:
        return False
    send = getattr(candidate, "send", None)
    if not callable(send):
        return False
    result = send(message)
    if inspect.isawaitable(result):
        await result
    return True


async def _post_raid_log(ctx: DispatchContext, raid: Any, sign: int, amount: int, user_ids: list[int], reason: str) -> bool:
    thread_id = _row_get(raid, "thread_id")
    if not thread_id:
        return False
    try:
        thread_id = int(thread_id)
    except Exception:
        return False

    action_word = "awarded" if sign > 0 else "deducted"
    preposition = "to" if sign > 0 else "from"
    short_reason = (reason or "").strip()
    if len(short_reason) > 200:
        short_reason = short_reason[:197] + "..."

    if len(user_ids) == 1:
        target_text = f"<@{int(user_ids[0])}>"
        message = f"AI: {_actor_mention(ctx)} {action_word} **{abs(int(amount))} DKP** {preposition} {target_text}."
    else:
        mentions = ", ".join(f"<@{int(user_id)}>" for user_id in user_ids)
        message = f"AI: {_actor_mention(ctx)} {action_word} **{abs(int(amount))} DKP** {preposition} **{len(user_ids)}** raid member(s).\n{mentions}"
    if short_reason:
        message = f"{message} ({short_reason})"
    if len(message) > 2000:
        message = f"AI: {_actor_mention(ctx)} {action_word} **{abs(int(amount))} DKP** {preposition} **{len(user_ids)}** raid member(s)."
        if short_reason:
            message = f"{message} ({short_reason})"

    guild = getattr(getattr(ctx, "interaction", None), "guild", None)
    for source in (guild, getattr(ctx, "bot", None)):
        if source is None:
            continue
        for method_name in ("get_thread", "get_channel_or_thread", "get_channel"):
            method = getattr(source, method_name, None)
            if not callable(method):
                continue
            try:
                candidate = method(thread_id)
                if inspect.isawaitable(candidate):
                    candidate = await candidate
                if await _send_to_candidate(candidate, message):
                    return True
            except Exception:
                continue

    fetch_channel = getattr(guild, "fetch_channel", None)
    if callable(fetch_channel):
        try:
            candidate = fetch_channel(thread_id)
            if inspect.isawaitable(candidate):
                candidate = await candidate
            if await _send_to_candidate(candidate, message):
                return True
        except Exception:
            return False
    return False


async def _record_raid_dkp_transactions(ctx: DispatchContext, raid: Any, user_ids: list[int], delta: int, reason: str) -> None:
    raid_id = _row_get(raid, "id")
    for user_id in user_ids:
        try:
            await ctx.bot.db.record_raid_dkp_transaction(
                int(raid_id),
                int(ctx.guild_id),
                int(user_id),
                int(delta),
                str(reason),
                actor_id=int(ctx.actor_id),
            )
        except Exception:
            logging.exception("Failed to record AI raid DKP transaction raid_id=%s user_id=%s", raid_id, user_id)


async def _apply(ctx: DispatchContext, args: dict[str, Any], sign: int, verb: str) -> DispatchResult:
    target = str(args.get("target", "")).strip()
    amount = int(args["amount"])
    reason = (args.get("reason") or f"voice/ai {verb}").strip()
    delta = sign * amount

    if target.lower() in _ALL_TOKENS:
        raid, member_ids = await _active_raid_roster(ctx)
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
        changes = []
        for user_id in member_ids:
            await ctx.bot.db.modify_user_dkp(user_id, ctx.guild_id, delta, reason)
            changes.append({"user_id": int(user_id), "delta": int(delta)})
        if raid is not None:
            await _record_raid_dkp_transactions(ctx, raid, member_ids, delta, reason)
            raid_log_posted = await _post_raid_log(ctx, raid, sign, amount, member_ids, reason)
        else:
            raid_log_posted = False
        return DispatchResult(
            status="ok",
            message=f"{verb.capitalize()}ed {amount} DKP {('to' if sign > 0 else 'from')} {len(member_ids)} raid member(s).",
            data={
                "count": len(member_ids),
                "amount": amount,
                "sign": sign,
                "raid_log_posted": raid_log_posted,
                "undo": {
                    "action": "dkp_changes",
                    "data": {"changes": changes, "reason": reason},
                },
            },
        )

    user_id = _resolve_target_id(target)
    if user_id is None:
        return DispatchResult(
            status="error",
            message=f"Couldn't understand the target '{target}'. Use a mention or 'all'.",
        )
    raid, member_ids = await _active_raid_roster(ctx)
    raid_target_ids = [user_id] if raid is not None and member_ids and int(user_id) in set(member_ids) else []
    await ctx.bot.db.modify_user_dkp(user_id, ctx.guild_id, delta, reason)
    if raid is not None and raid_target_ids:
        await _record_raid_dkp_transactions(ctx, raid, raid_target_ids, delta, reason)
        raid_log_posted = await _post_raid_log(ctx, raid, sign, amount, raid_target_ids, reason)
    else:
        raid_log_posted = False
    return DispatchResult(
        status="ok",
        message=f"{verb.capitalize()}ed {amount} DKP {('to' if sign > 0 else 'from')} <@{user_id}>.",
        data={
            "user_id": user_id,
            "amount": amount,
            "sign": sign,
            "raid_log_posted": raid_log_posted,
            "undo": {
                "action": "dkp_changes",
                "data": {"changes": [{"user_id": int(user_id), "delta": int(delta)}], "reason": reason},
            },
        },
    )


async def award_dkp(args: dict[str, Any], ctx: DispatchContext) -> DispatchResult:
    return await _apply(ctx, args, sign=1, verb="award")


async def deduct_dkp(args: dict[str, Any], ctx: DispatchContext) -> DispatchResult:
    return await _apply(ctx, args, sign=-1, verb="deduct")
