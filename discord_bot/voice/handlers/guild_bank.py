"""Guild-bank handlers for the voice AI command platform.

Reuse ``bot.db.guild_bank_find_by_name`` / ``guild_bank_withdraw`` /
``guild_bank_deposit`` / ``guild_bank_get_inventory``.
"""

from __future__ import annotations

from typing import Any

from ..dispatch import DispatchContext, DispatchResult


_VALID_CATEGORIES = {
    "ship_component",
    "commodities",
    "consumable",
    "equipment",
    "currency",
    "other",
}

_NOTE = "voice/ai command"


async def bank_withdraw(args: dict[str, Any], ctx: DispatchContext) -> DispatchResult:
    item_name = str(args.get("item_name", "")).strip()
    quantity = int(args["quantity"])

    item = await ctx.bot.db.guild_bank_find_by_name(ctx.guild_id, item_name)
    if not item:
        inventory = await ctx.bot.db.guild_bank_get_inventory(ctx.guild_id)
        names = []
        for row in inventory or []:
            try:
                names.append(str(row["item_name"]))
            except Exception:
                continue
        if names:
            preview = ", ".join(names[:10])
            hint = f" In the bank: {preview}."
        else:
            hint = " The bank is empty."
        return DispatchResult(
            status="error",
            message=f"No bank item named '{item_name}' found.{hint}",
        )

    item_id = int(item["id"])
    ok = await ctx.bot.db.guild_bank_withdraw(
        ctx.guild_id, item_id, quantity, ctx.actor_id, note=_NOTE
    )
    if not ok:
        return DispatchResult(
            status="error",
            message=f"Couldn't withdraw {quantity} of '{item['item_name']}' (insufficient quantity).",
        )
    return DispatchResult(
        status="ok",
        message=f"Withdrew {quantity} of '{item['item_name']}' from the guild bank.",
        data={"item_id": item_id, "quantity": quantity},
    )


async def bank_deposit(args: dict[str, Any], ctx: DispatchContext) -> DispatchResult:
    item_name = str(args.get("item_name", "")).strip()
    quantity = int(args["quantity"])
    category = str(args.get("category") or "other")
    if category not in _VALID_CATEGORIES:
        category = "other"
    location = str(args.get("location") or "")
    held_by = args.get("held_by_user_id")
    held_by_user_id = int(held_by) if held_by is not None else int(ctx.actor_id)

    item_id = await ctx.bot.db.guild_bank_deposit(
        ctx.guild_id,
        item_name,
        quantity,
        category,
        location,
        held_by_user_id,
        ctx.actor_id,
        note=_NOTE,
    )
    return DispatchResult(
        status="ok",
        message=f"Deposited {quantity} of '{item_name}' into the guild bank.",
        data={"item_id": item_id, "quantity": quantity, "category": category},
    )
