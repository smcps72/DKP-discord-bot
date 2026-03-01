import asyncio
import discord
import logging
from discord.ext import commands
from discord import app_commands
from ..utils import (
    create_info_embed,
    create_success_embed,
    create_error_embed,
    is_officer,
)


BANK_CATEGORIES = [
    app_commands.Choice(name="Ship Component", value="ship_component"),
    app_commands.Choice(name="Commodities", value="commodities"),
    app_commands.Choice(name="Consumable", value="consumable"),
    app_commands.Choice(name="Equipment", value="equipment"),
    app_commands.Choice(name="Currency", value="currency"),
    app_commands.Choice(name="Other", value="other"),
]


class GuildBankCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._inventory_sync_locks: dict[int, asyncio.Lock] = {}

    # ------------------------------------------------------------------
    # Slash commands
    # ------------------------------------------------------------------

    async def held_by_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        if not interaction.guild:
            return []
        try:
            config = await self.bot.db.get_guild_config(interaction.guild.id)
        except Exception:
            config = None

        raider_role = None
        if config and "raider_role_id" in config.keys() and config["raider_role_id"]:
            raider_role = interaction.guild.get_role(int(config["raider_role_id"]))
        if raider_role is None:
            for role in interaction.guild.roles:
                if (role.name or "").strip().casefold() == "raider":
                    raider_role = role
                    break

        members = [
            m for m in (raider_role.members if raider_role else interaction.guild.members)
            if not m.bot
        ]
        lowered = current.lower()
        return [
            app_commands.Choice(name=m.display_name, value=str(m.id))
            for m in members
            if not lowered or lowered in m.display_name.lower() or lowered in m.name.lower()
        ][:25]

    @app_commands.command(
        name="bank_deposit",
        description="Deposit an item into the guild bank. Officers only.",
    )
    @app_commands.describe(
        item_name="Name of the item to deposit",
        quantity="How many to deposit",
        category="Item category",
        location="Where the item is stored (e.g. bank alt name, guild vault tab)",
        held_by="The guild member physically holding the item",
        note="Optional note for the transaction log",
    )
    @app_commands.choices(category=BANK_CATEGORIES)
    @app_commands.autocomplete(held_by=held_by_autocomplete)
    @app_commands.check(is_officer)
    async def bank_deposit_cmd(
        self,
        interaction: discord.Interaction,
        item_name: str,
        quantity: int,
        category: app_commands.Choice[str],
        location: str,
        held_by: str,
        note: str = "",
    ):
        if interaction.guild is None:
            return await interaction.response.send_message(
                "This command cannot be used in DMs.", ephemeral=True
            )

        if quantity <= 0:
            return await interaction.response.send_message(
                "Quantity must be greater than 0.", ephemeral=True
            )

        item_name = item_name.strip()
        if not item_name:
            return await interaction.response.send_message(
                "Item name cannot be empty.", ephemeral=True
            )
        if len(item_name) > 100:
            item_name = item_name[:100]

        location = (location or "").strip()
        if len(location) > 100:
            location = location[:100]

        note = (note or "").strip()
        if len(note) > 300:
            note = note[:300]

        held_by_member: discord.Member | discord.User | None = None
        if held_by:
            try:
                member_id = int(held_by)
                held_by_member = interaction.guild.get_member(member_id)
                if held_by_member is None:
                    try:
                        held_by_member = await interaction.guild.fetch_member(member_id)
                    except (discord.NotFound, discord.HTTPException):
                        pass
            except (ValueError, TypeError):
                held_by_member = interaction.guild.get_member_named(held_by)
        if held_by_member is None:
            held_by_member = interaction.user

        if not interaction.response.is_done():
            await interaction.response.defer()

        item_id = await self.bot.db.guild_bank_deposit(
            guild_id=interaction.guild.id,
            item_name=item_name,
            quantity=quantity,
            category=category.value,
            location=location,
            held_by_user_id=held_by_member.id,
            actor_id=interaction.user.id,
            note=note,
        )

        await self._post_transaction_notification(
            interaction.guild,
            action="deposit",
            item_id=item_id,
            item_name=item_name,
            quantity=quantity,
            category=category.value,
            location=location,
            held_by_user_id=held_by_member.id,
            actor_id=interaction.user.id,
            note=note,
        )

        embed = create_success_embed(
            "Item Deposited",
            f"**{quantity}x {item_name}** deposited into the guild bank.\n"
            f"Category: `{category.value}`\n"
            f"Location: `{location}`\n"
            f"Held by: {held_by_member.mention}\n"
            f"Item ID: `{item_id}`",
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

        await self._update_bank_panel(interaction.guild)

    @app_commands.command(
        name="bank_withdraw",
        description="Withdraw an item from the guild bank. Officers only.",
    )
    @app_commands.describe(
        item_id="The ID of the item to withdraw (use /bank_inventory to find IDs)",
        quantity="How many to withdraw",
        note="Optional note for the transaction log",
    )
    @app_commands.check(is_officer)
    async def bank_withdraw_cmd(
        self,
        interaction: discord.Interaction,
        item_id: int,
        quantity: int,
        note: str = "",
    ):
        if interaction.guild is None:
            return await interaction.response.send_message(
                "This command cannot be used in DMs.", ephemeral=True
            )

        if quantity <= 0:
            return await interaction.response.send_message(
                "Quantity must be greater than 0.", ephemeral=True
            )

        note = (note or "").strip()
        if len(note) > 300:
            note = note[:300]

        if not interaction.response.is_done():
            await interaction.response.defer()

        item = await self.bot.db.guild_bank_get_item(item_id, interaction.guild.id)
        if not item:
            embed = create_error_embed(
                "Item Not Found",
                f"No guild bank item found with ID `{item_id}`.",
            )
            return await interaction.followup.send(embed=embed, ephemeral=True)

        success = await self.bot.db.guild_bank_withdraw(
            guild_id=interaction.guild.id,
            item_id=item_id,
            quantity=quantity,
            actor_id=interaction.user.id,
            note=note,
        )

        if not success:
            current_qty = int(item["quantity"])
            embed = create_error_embed(
                "Withdrawal Failed",
                f"Cannot withdraw **{quantity}** — only **{current_qty}** of "
                f"**{item['item_name']}** available.",
            )
            return await interaction.followup.send(embed=embed, ephemeral=True)

        embed = create_success_embed(
            "Item Withdrawn",
            f"**{quantity}x {item['item_name']}** withdrawn from the guild bank.\n"
            f"Item ID: `{item_id}`",
        )
        await self._post_transaction_notification(
            interaction.guild,
            action="withdraw",
            item_id=item_id,
            item_name=item["item_name"],
            quantity=quantity,
            category=item["category"] or "other",
            location=item["location"] or "",
            held_by_user_id=item["held_by_user_id"],
            actor_id=interaction.user.id,
            note=note,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

        await self._update_bank_panel(interaction.guild)

    @app_commands.command(
        name="bank_inventory",
        description="View all items currently in the guild bank.",
    )
    async def bank_inventory_cmd(self, interaction: discord.Interaction):
        if interaction.guild is None:
            return await interaction.response.send_message(
                "This command cannot be used in DMs.", ephemeral=True
            )

        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)

        items = await self.bot.db.guild_bank_get_inventory(interaction.guild.id)
        if not items:
            embed = create_info_embed(
                "Guild Bank Inventory",
                "The guild bank is empty.",
            )
            return await interaction.followup.send(embed=embed, ephemeral=True)

        embed = self._build_inventory_embed(items, interaction.guild)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(
        name="bank_log",
        description="View the guild bank transaction log (papertrail).",
    )
    @app_commands.describe(limit="How many transactions to show (1-25)")
    async def bank_log_cmd(
        self, interaction: discord.Interaction, limit: int = 15
    ):
        if interaction.guild is None:
            return await interaction.response.send_message(
                "This command cannot be used in DMs.", ephemeral=True
            )

        limit = max(1, min(int(limit), 25))

        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)

        rows = await self.bot.db.guild_bank_get_transactions(
            interaction.guild.id, limit=limit
        )
        if not rows:
            embed = create_info_embed(
                "Guild Bank Log",
                "No transactions recorded yet.",
            )
            return await interaction.followup.send(embed=embed, ephemeral=True)

        embed = self._build_log_embed(rows, interaction.guild)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(
        name="bank_panel",
        description="Post the guild bank panel in the current channel. Officers only.",
    )
    @app_commands.check(is_officer)
    async def bank_panel_cmd(self, interaction: discord.Interaction):
        if interaction.guild is None:
            return await interaction.response.send_message(
                "This command cannot be used in DMs.", ephemeral=True
            )

        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)

        embed = create_info_embed(
            "Guild Bank",
            "Use the buttons below to deposit or withdraw items.",
        )

        from ..ui.views import GuildBankPanelView

        view = GuildBankPanelView(self.bot)
        msg = await interaction.channel.send(embed=embed, view=view)

        await interaction.followup.send(
            f"Guild bank panel posted: {msg.jump_url}", ephemeral=True
        )

    # ------------------------------------------------------------------
    # Deposit / withdraw from panel buttons (called by views)
    # ------------------------------------------------------------------

    async def process_deposit(
        self,
        interaction: discord.Interaction,
        item_name: str,
        quantity_str: str,
        category: str,
        location: str,
        held_by_name: str = "",
        note: str = "",
    ):
        guild = getattr(interaction, "guild", None)
        if not guild:
            return

        item_name = (item_name or "").strip()
        if not item_name:
            return await interaction.response.send_message(
                "Item name cannot be empty.", ephemeral=True
            )
        if len(item_name) > 100:
            item_name = item_name[:100]

        try:
            quantity = int(quantity_str)
        except (ValueError, TypeError):
            return await interaction.response.send_message(
                "Quantity must be a whole number.", ephemeral=True
            )
        if quantity <= 0:
            return await interaction.response.send_message(
                "Quantity must be greater than 0.", ephemeral=True
            )

        category = (category or "other").strip().lower()
        valid_categories = {c.value for c in BANK_CATEGORIES}
        if category not in valid_categories:
            return await interaction.response.send_message(
                f"Invalid category `{category}`. Valid options: {', '.join(sorted(valid_categories))}.",
                ephemeral=True,
            )
        location = (location or "").strip()[:100]
        note = (note or "").strip()[:300]

        held_by_name = (held_by_name or "").strip()
        held_by: discord.Member | None = None
        if held_by_name:
            lower = held_by_name.lower()
            held_by = discord.utils.find(
                lambda m: m.display_name.lower() == lower or m.name.lower() == lower,
                guild.members,
            )
            if held_by is None:
                return await interaction.response.send_message(
                    f"Could not find member `{held_by_name}`. Check the exact display name and try again.",
                    ephemeral=True,
                )
        else:
            held_by = interaction.user

        if not interaction.response.is_done():
            await interaction.response.defer()

        item_id = await self.bot.db.guild_bank_deposit(
            guild_id=guild.id,
            item_name=item_name,
            quantity=quantity,
            category=category,
            location=location,
            held_by_user_id=held_by.id,
            actor_id=interaction.user.id,
            note=note,
        )

        await self._post_transaction_notification(
            guild,
            action="deposit",
            item_id=item_id,
            item_name=item_name,
            quantity=quantity,
            category=category,
            location=location,
            held_by_user_id=held_by.id,
            actor_id=interaction.user.id,
            note=note,
        )

        embed = create_success_embed(
            "Item Deposited",
            f"**{quantity}x {item_name}** deposited into the guild bank.\n"
            f"Category: `{category}`\n"
            f"Location: `{location}`\n"
            f"Held by: {held_by.mention}\n"
            f"Item ID: `{item_id}`",
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

        await self._update_bank_panel(guild)

    async def process_withdraw(
        self,
        interaction: discord.Interaction,
        item_id_str: str,
        quantity_str: str,
        note: str = "",
    ):
        guild = getattr(interaction, "guild", None)
        if not guild:
            return

        try:
            item_id = int(item_id_str)
        except (ValueError, TypeError):
            return await interaction.response.send_message(
                "Item ID must be a whole number.", ephemeral=True
            )

        try:
            quantity = int(quantity_str)
        except (ValueError, TypeError):
            return await interaction.response.send_message(
                "Quantity must be a whole number.", ephemeral=True
            )
        if quantity <= 0:
            return await interaction.response.send_message(
                "Quantity must be greater than 0.", ephemeral=True
            )

        note = (note or "").strip()[:300]

        if not interaction.response.is_done():
            await interaction.response.defer()

        item = await self.bot.db.guild_bank_get_item(item_id, guild.id)
        if not item:
            embed = create_error_embed(
                "Item Not Found",
                f"No guild bank item found with ID `{item_id}`.",
            )
            return await interaction.followup.send(embed=embed, ephemeral=True)

        success = await self.bot.db.guild_bank_withdraw(
            guild_id=guild.id,
            item_id=item_id,
            quantity=quantity,
            actor_id=interaction.user.id,
            note=note,
        )

        if not success:
            current_qty = int(item["quantity"])
            embed = create_error_embed(
                "Withdrawal Failed",
                f"Cannot withdraw **{quantity}** — only **{current_qty}** of "
                f"**{item['item_name']}** available.",
            )
            return await interaction.followup.send(embed=embed, ephemeral=True)

        embed = create_success_embed(
            "Item Withdrawn",
            f"**{quantity}x {item['item_name']}** withdrawn from the guild bank.\n"
            f"Item ID: `{item_id}`",
        )
        await self._post_transaction_notification(
            guild,
            action="withdraw",
            item_id=item_id,
            item_name=item["item_name"],
            quantity=quantity,
            category=item["category"] or "other",
            location=item["location"] or "",
            held_by_user_id=item["held_by_user_id"],
            actor_id=interaction.user.id,
            note=note,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

        await self._update_bank_panel(guild)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_inventory_embed(
        self, items, guild: discord.Guild
    ) -> discord.Embed:
        if not items:
            return create_info_embed(
                "Guild Bank Inventory", "The guild bank is empty."
            )

        categories: dict[str, list[str]] = {}
        for item in items:
            cat = (item["category"] or "other").capitalize()
            qty = int(item["quantity"])
            name = item["item_name"]
            loc = item["location"] or "—"
            holder_id = item["held_by_user_id"]
            if holder_id:
                member = guild.get_member(int(holder_id))
                holder_str = member.display_name if member else str(holder_id)
            else:
                holder_str = "—"
            line = f"`#{item['id']}` **{name}** ×{qty}  📍{loc}  👤{holder_str}"
            categories.setdefault(cat, []).append(line)

        desc_parts: list[str] = []
        for cat_name in sorted(categories.keys()):
            desc_parts.append(f"__**{cat_name}**__")
            desc_parts.extend(categories[cat_name])
            desc_parts.append("")

        description = "\n".join(desc_parts).strip()
        if len(description) > 4000:
            description = description[:3997] + "..."

        return create_info_embed("Guild Bank Inventory", description)

    def _build_log_embed(self, rows, guild: discord.Guild) -> discord.Embed:
        if not rows:
            return create_info_embed(
                "Guild Bank Transaction Log", "No transactions recorded yet."
            )
        lines: list[str] = []
        for r in rows:
            action = r["action"]
            emoji = "📥" if action == "deposit" else "📤"
            qty = int(r["quantity"])
            name = r["item_name"]
            actor_member = guild.get_member(int(r["actor_id"]))
            actor = actor_member.display_name if actor_member else str(r["actor_id"])
            ts = r["timestamp"]
            note = (r["note"] or "").strip()
            note_str = f" — {note}" if note else ""

            lines.append(
                f"`{ts}` {emoji} **{qty}x {name}** by {actor}{note_str}"
            )

        description = "\n".join(lines)
        if len(description) > 4000:
            description = description[:3997] + "..."

        return create_info_embed("Guild Bank Transaction Log", description)

    def _build_inventory_item_message(self, item, guild: discord.Guild | None = None) -> str:
        item_id = int(item["id"])
        qty = int(item["quantity"])
        name = str(item["item_name"] or "Unknown Item")
        category = str(item["category"] or "other")
        location = str(item["location"] or "—")
        holder_id = item["held_by_user_id"]
        if holder_id and guild:
            member = guild.get_member(int(holder_id))
            holder_str = member.display_name if member else str(holder_id)
        elif holder_id:
            holder_str = str(holder_id)
        else:
            holder_str = "—"
        return (
            f"`#{item_id}` **{name}** ×{qty}\n"
            f"Category: `{category}`\n"
            f"Location: `{location}`\n"
            f"Held by: {holder_str}"
        )

    def _build_transaction_message(
        self,
        *,
        action: str,
        item_id: int,
        item_name: str,
        quantity: int,
        category: str,
        location: str,
        held_by_display: str,
        actor_display: str,
        note: str = "",
    ) -> str:
        emoji = "📥" if action == "deposit" else "📤"
        note_str = f"\nNote: {note}" if (note or "").strip() else ""
        return (
            f"{emoji} **{action.title()}** — `#{item_id}` **{item_name}** ×{int(quantity)}\n"
            f"Category: `{category}`\n"
            f"Location: `{location or '—'}`\n"
            f"Held by: {held_by_display or '—'}\n"
            f"Logger: {actor_display}"
            f"{note_str}"
        )

    async def _resolve_config_channel(self, guild: discord.Guild, channel_id):
        if not channel_id:
            return None
        channel = guild.get_channel(int(channel_id))
        if channel is None:
            try:
                channel = await guild.fetch_channel(int(channel_id))
            except Exception:
                return None
        return channel

    async def _post_transaction_notification(
        self,
        guild: discord.Guild,
        *,
        action: str,
        item_id: int,
        item_name: str,
        quantity: int,
        category: str,
        location: str,
        held_by_user_id: int | None,
        actor_id: int,
        note: str = "",
    ):
        try:
            config = await self.bot.db.get_guild_config(guild.id)
        except Exception:
            return

        if not config or "guild_bank_transactions_channel_id" not in config.keys():
            return

        channel = await self._resolve_config_channel(
            guild,
            config["guild_bank_transactions_channel_id"],
        )
        if channel is None or not hasattr(channel, "send"):
            return

        held_by_display = "—"
        if held_by_user_id:
            member = guild.get_member(int(held_by_user_id))
            held_by_display = member.display_name if member else str(held_by_user_id)
        actor_member = guild.get_member(int(actor_id))
        actor_display = actor_member.display_name if actor_member else str(actor_id)

        try:
            await channel.send(
                self._build_transaction_message(
                    action=action,
                    item_id=item_id,
                    item_name=item_name,
                    quantity=quantity,
                    category=category,
                    location=location,
                    held_by_display=held_by_display,
                    actor_display=actor_display,
                    note=note,
                ),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except Exception:
            logging.exception("Failed to send guild bank transaction notification")

    async def _sync_inventory_channel(self, guild: discord.Guild):
        guild_id = int(guild.id)
        lock = self._inventory_sync_locks.setdefault(guild_id, asyncio.Lock())
        async with lock:
            try:
                config = await self.bot.db.get_guild_config(guild.id)
            except Exception:
                return

            if not config or "guild_bank_inventory_channel_id" not in config.keys():
                return

            inventory_channel = await self._resolve_config_channel(
                guild,
                config["guild_bank_inventory_channel_id"],
            )
            if inventory_channel is None or not hasattr(inventory_channel, "send"):
                return

            try:
                items = await self.bot.db.guild_bank_get_inventory(guild.id)
                mappings = await self.bot.db.guild_bank_list_inventory_messages(guild.id)
            except Exception:
                logging.exception("Failed loading guild bank inventory state")
                return

            items_by_id = {int(item["id"]): item for item in list(items or [])}

            for row in list(mappings or []):
                item_id = int(row["item_id"])
                if item_id in items_by_id:
                    continue

                channel = inventory_channel
                if int(row["channel_id"]) != getattr(inventory_channel, "id", 0):
                    channel = await self._resolve_config_channel(guild, row["channel_id"])
                try:
                    if channel is not None and hasattr(channel, "fetch_message"):
                        msg = await channel.fetch_message(int(row["message_id"]))
                        await msg.delete()
                except Exception:
                    pass
                try:
                    await self.bot.db.guild_bank_delete_inventory_message(guild.id, item_id)
                except Exception:
                    pass

            for item_id, item in items_by_id.items():
                content = self._build_inventory_item_message(item, guild)
                mapping = None
                try:
                    mapping = await self.bot.db.guild_bank_get_inventory_message(guild.id, item_id)
                except Exception:
                    mapping = None

                target_msg = None
                if mapping is not None:
                    mapped_channel = inventory_channel
                    if int(mapping["channel_id"]) != getattr(inventory_channel, "id", 0):
                        mapped_channel = await self._resolve_config_channel(guild, mapping["channel_id"])
                    if mapped_channel is not None and hasattr(mapped_channel, "fetch_message"):
                        try:
                            target_msg = await mapped_channel.fetch_message(int(mapping["message_id"]))
                            if mapped_channel.id != inventory_channel.id:
                                await target_msg.delete()
                                target_msg = None
                        except Exception:
                            target_msg = None

                try:
                    if target_msg is None:
                        target_msg = await inventory_channel.send(
                            content,
                            allowed_mentions=discord.AllowedMentions.none(),
                        )
                    else:
                        await target_msg.edit(
                            content=content,
                            allowed_mentions=discord.AllowedMentions.none(),
                        )


                    await self.bot.db.guild_bank_set_inventory_message(
                        guild.id,
                        item_id,
                        inventory_channel.id,
                        target_msg.id,
                    )
                except Exception:
                    logging.exception("Failed to sync inventory message for item_id=%s", item_id)

    async def _update_bank_panel(self, guild: discord.Guild):
        """Keep guild bank panel static and synchronize searchable inventory channel messages."""
        try:
            config = await self.bot.db.get_guild_config(guild.id)
        except Exception:
            return

        await self._sync_inventory_channel(guild)

        bank_channel_id = None
        if config and "guild_bank_channel_id" in config.keys():
            bank_channel_id = config["guild_bank_channel_id"]

        if not bank_channel_id:
            return

        channel = guild.get_channel(int(bank_channel_id))
        if channel is None:
            try:
                channel = await guild.fetch_channel(int(bank_channel_id))
            except Exception:
                return

        if channel is None or not hasattr(channel, "history"):
            return

        embed = create_info_embed(
            "Guild Bank",
            "Use the buttons below to deposit or withdraw items.",
        )

        bot_user = self.bot.user
        if bot_user is None:
            return

        try:
            async for msg in channel.history(limit=30):
                if msg.author.id != bot_user.id:
                    continue
                for emb in list(getattr(msg, "embeds", []) or []):
                    if (getattr(emb, "title", None) or "").strip() in {"Guild Bank", "Guild Bank Inventory"}:
                        try:
                            from ..ui.views import GuildBankPanelView

                            await msg.edit(embed=embed, view=GuildBankPanelView(self.bot))
                        except Exception:
                            logging.exception("Failed to edit guild bank panel message")
                        return
        except Exception:
            logging.exception("Failed to scan for guild bank panel message")


async def setup(bot: commands.Bot):
    await bot.add_cog(GuildBankCog(bot))
