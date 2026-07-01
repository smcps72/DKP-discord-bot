from __future__ import annotations

from typing import Any

from ..dispatch import DispatchContext, DispatchResult


_NOTE = "undo command"


async def _mark_undone(ctx: DispatchContext, entry_id: int) -> DispatchResult | None:
    marked = await ctx.bot.db.mark_command_undo_entry_undone(entry_id)
    if marked:
        return None
    return DispatchResult(
        status="error",
        message="That command was already undone.",
    )


async def _undo_dkp_changes(ctx: DispatchContext, entry: dict[str, Any]) -> DispatchResult:
    entry_id = int(entry["id"])
    data = entry.get("undo_data") or {}
    changes = list(data.get("changes") or [])
    if not changes:
        return DispatchResult(status="error", message="That command has no DKP changes to undo.")

    applied = 0
    for change in changes:
        user_id = int(change["user_id"])
        delta = int(change["delta"])
        reverse_delta = -delta
        if reverse_delta == 0:
            continue
        await ctx.bot.db.modify_user_dkp(
            user_id,
            ctx.guild_id,
            reverse_delta,
            f"Undo AI command: {entry['command_name']}",
        )
        applied += 1

    marker_error = await _mark_undone(ctx, entry_id)
    if marker_error is not None:
        return marker_error
    return DispatchResult(
        status="ok",
        message=f"Undid `{entry['command_name']}` for {applied} DKP change(s).",
    )


async def _undo_bank_deposit(ctx: DispatchContext, entry: dict[str, Any]) -> DispatchResult:
    entry_id = int(entry["id"])
    data = entry.get("undo_data") or {}
    item_id = int(data["item_id"])
    quantity = int(data["quantity"])
    item = await ctx.bot.db.guild_bank_get_item(item_id, ctx.guild_id)
    if not item:
        return DispatchResult(
            status="error",
            message="Couldn't undo that deposit because the guild bank item no longer exists.",
        )
    if (
        str(item["item_name"]) != str(data.get("item_name"))
        or str(item["category"] or "other") != str(data.get("category") or "other")
        or str(item["location"] or "") != str(data.get("location") or "")
        or int(item["held_by_user_id"] or ctx.actor_id) != int(data.get("held_by_user_id") or ctx.actor_id)
    ):
        return DispatchResult(
            status="error",
            message="Couldn't undo that deposit because the guild bank item no longer matches the original command.",
        )
    ok = await ctx.bot.db.guild_bank_withdraw(
        ctx.guild_id,
        item_id,
        quantity,
        ctx.actor_id,
        note=_NOTE,
    )
    if not ok:
        return DispatchResult(
            status="error",
            message="Couldn't undo that deposit because the item no longer has enough quantity in the guild bank.",
        )

    marker_error = await _mark_undone(ctx, entry_id)
    if marker_error is not None:
        return marker_error
    return DispatchResult(
        status="ok",
        message=f"Undid `{entry['command_name']}` by withdrawing {quantity} deposited item(s).",
    )


async def _undo_bank_withdraw(ctx: DispatchContext, entry: dict[str, Any]) -> DispatchResult:
    entry_id = int(entry["id"])
    data = entry.get("undo_data") or {}
    quantity = int(data["quantity"])
    item_name = str(data["item_name"])
    await ctx.bot.db.guild_bank_deposit(
        ctx.guild_id,
        item_name,
        quantity,
        str(data.get("category") or "other"),
        str(data.get("location") or ""),
        int(data.get("held_by_user_id") or ctx.actor_id),
        ctx.actor_id,
        note=_NOTE,
    )

    marker_error = await _mark_undone(ctx, entry_id)
    if marker_error is not None:
        return marker_error
    return DispatchResult(
        status="ok",
        message=f"Undid `{entry['command_name']}` by depositing {quantity} of '{item_name}' back into the guild bank.",
    )


async def undo_last_command(args: dict[str, Any], ctx: DispatchContext) -> DispatchResult:
    entry = await ctx.bot.db.get_last_pending_command_undo(ctx.guild_id, ctx.actor_id)
    if not entry:
        return DispatchResult(
            status="error",
            message="You don't have a recent undoable AI command in this server.",
        )

    action = str(entry.get("undo_action") or "")
    if action == "dkp_changes":
        return await _undo_dkp_changes(ctx, entry)
    if action == "bank_deposit":
        return await _undo_bank_deposit(ctx, entry)
    if action == "bank_withdraw":
        return await _undo_bank_withdraw(ctx, entry)
    return DispatchResult(
        status="error",
        message=f"The last command has unsupported undo action '{action}'.",
    )
