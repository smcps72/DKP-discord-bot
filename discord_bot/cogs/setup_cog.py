import discord
from discord.ext import commands
from discord import app_commands
from ..ui.views import WelcomeView, GuildBankPanelView, AuctionControlPanelView
from ..utils import create_info_embed, is_admin
import logging

class SetupCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _ensure_auction_channels(self, guild: discord.Guild, config, archive_category, dkp_channel) -> bool:
        """Ensure completed-auctions channel and auction panel message exist."""
        changed = False

        def _is_category_channel(ch) -> bool:
            return isinstance(ch, discord.CategoryChannel) or (
                ch is not None and hasattr(ch, "create_text_channel") and hasattr(ch, "text_channels")
            )

        def _is_text_channel(ch) -> bool:
            return isinstance(ch, discord.TextChannel) or (ch is not None and hasattr(ch, "send"))

        keys = set(getattr(config, "keys", lambda: [])()) if config else set()

        def _cfg(key: str):
            return config[key] if config and key in keys else None

        completed_auctions_channel_id = _cfg("completed_auctions_channel_id")
        completed_auctions_channel = guild.get_channel(completed_auctions_channel_id) if completed_auctions_channel_id else None
        if not _is_text_channel(completed_auctions_channel):
            completed_auctions_channel = None
            if _is_category_channel(archive_category):
                for ch in archive_category.text_channels:
                    if (ch.name or "").lower() == "completed-auctions":
                        completed_auctions_channel = ch
                        break
            if not _is_text_channel(completed_auctions_channel) and _is_category_channel(archive_category):
                completed_auctions_channel = await archive_category.create_text_channel("completed-auctions")
                changed = True

        if _is_text_channel(completed_auctions_channel):
            if _cfg("completed_auctions_channel_id") != completed_auctions_channel.id:
                await self.bot.db.execute(
                    "UPDATE guilds SET completed_auctions_channel_id = ? WHERE guild_id = ?",
                    (completed_auctions_channel.id, guild.id),
                )
                changed = True

        if _is_text_channel(dkp_channel):
            auction_panel_message_id = _cfg("auction_panel_message_id")
            existing_msg = None
            if auction_panel_message_id:
                try:
                    existing_msg = await dkp_channel.fetch_message(auction_panel_message_id)
                except Exception:
                    existing_msg = None
            if existing_msg is None:
                embed = create_info_embed(
                    "💎 Community Auctions",
                    "Click the button below to open the Auction Panel. "
                    "Officers can start and end auctions; all guild members can place bids.",
                )
                view = AuctionControlPanelView(self.bot)
                try:
                    auction_msg = await dkp_channel.send(embed=embed, view=view)
                    await self.bot.db.execute(
                        "UPDATE guilds SET auction_panel_message_id = ? WHERE guild_id = ?",
                        (auction_msg.id, guild.id),
                    )
                    changed = True
                except Exception:
                    logging.exception("Failed to send auction panel message")

        return changed

    async def _ensure_guild_bank_channels(
        self,
        guild: discord.Guild,
        config,
        overwrites,
        dkp_category=None,
    ):
        """Ensure Guild Bank category + channels exist and are linked in config."""
        changed = False

        def _is_category_channel(ch) -> bool:
            return isinstance(ch, discord.CategoryChannel) or (
                ch is not None and hasattr(ch, "create_text_channel") and hasattr(ch, "text_channels")
            )

        def _is_text_channel(ch) -> bool:
            return isinstance(ch, discord.TextChannel) or (ch is not None and hasattr(ch, "send"))

        keys = set(getattr(config, "keys", lambda: [])()) if config else set()

        def _cfg(key: str):
            return config[key] if config and key in keys else None

        bank_category_id = _cfg("guild_bank_category_id")
        bank_category = guild.get_channel(bank_category_id) if bank_category_id else None
        if not _is_category_channel(bank_category):
            bank_category = None
            for ch in guild.categories:
                if (ch.name or "").strip().lower() in {"guild bank", "guild-bank"}:
                    bank_category = ch
                    break
            if bank_category is None:
                bank_category = await guild.create_category("Guild Bank", overwrites=overwrites)
                changed = True

        if _cfg("guild_bank_category_id") != getattr(bank_category, "id", None):
            await self.bot.db.execute(
                "UPDATE guilds SET guild_bank_category_id = ? WHERE guild_id = ?",
                (bank_category.id, guild.id),
            )
            changed = True

        update_channel_id_queries = {
            "guild_bank_channel_id": "UPDATE guilds SET guild_bank_channel_id = ? WHERE guild_id = ?",
            "guild_bank_inventory_channel_id": "UPDATE guilds SET guild_bank_inventory_channel_id = ? WHERE guild_id = ?",
            "guild_bank_transactions_channel_id": "UPDATE guilds SET guild_bank_transactions_channel_id = ? WHERE guild_id = ?",
        }

        async def _ensure_channel(col_name: str, channel_name: str, allow_legacy_dkp_lookup: bool = False):
            nonlocal changed
            ch_id = _cfg(col_name)
            channel = guild.get_channel(ch_id) if ch_id else None

            if not _is_text_channel(channel):
                channel = None
                for ch in bank_category.text_channels:
                    if (ch.name or "").lower() == channel_name:
                        channel = ch
                        break

            if channel is None and allow_legacy_dkp_lookup and dkp_category is not None:
                for ch in getattr(dkp_category, "text_channels", []):
                    if (ch.name or "").lower() == channel_name:
                        channel = ch
                        break

            if channel is None:
                channel = await bank_category.create_text_channel(channel_name)
                changed = True

            if getattr(channel, "category_id", None) != bank_category.id:
                try:
                    await channel.edit(category=bank_category)
                except Exception:
                    pass

            if _cfg(col_name) != channel.id:
                query = update_channel_id_queries.get(col_name)
                if query is None:
                    raise ValueError(f"Unsupported guild bank channel column: {col_name}")
                await self.bot.db.execute(
                    query,
                    (channel.id, guild.id),
                )
                changed = True

            return channel

        panel_channel = await _ensure_channel(
            "guild_bank_channel_id",
            "guild-bank",
            allow_legacy_dkp_lookup=True,
        )
        inventory_channel = await _ensure_channel(
            "guild_bank_inventory_channel_id",
            "inventory",
        )
        transactions_channel = await _ensure_channel(
            "guild_bank_transactions_channel_id",
            "transactions",
        )

        return bank_category, panel_channel, inventory_channel, transactions_channel, changed

    async def _ensure_guild_bank_panel_message(
        self,
        panel_channel,
        inventory_channel,
        transactions_channel,
    ) -> bool:
        """Ensure a single persistent Guild Bank panel message exists in the panel channel."""
        if panel_channel is None or not hasattr(panel_channel, "history"):
            return False

        inventory_ref = f"<#{inventory_channel.id}>" if inventory_channel else "(not configured)"
        transactions_ref = f"<#{transactions_channel.id}>" if transactions_channel else "(not configured)"
        embed = create_info_embed(
            "Guild Bank",
            "Use the buttons below to deposit or withdraw items.\n"
            f"Inventory is searchable in {inventory_ref}.\n"
            f"Transaction history is posted in {transactions_ref}.",
        )
        view = GuildBankPanelView(self.bot)

        bot_user = self.bot.user
        target = None
        try:
            async for msg in panel_channel.history(limit=50):
                if bot_user is not None and getattr(msg.author, "id", None) != bot_user.id:
                    continue
                for emb in list(getattr(msg, "embeds", []) or []):
                    title = (getattr(emb, "title", None) or "").strip()
                    if title in {"Guild Bank", "Guild Bank Inventory"}:
                        target = msg
                        break
                if target is not None:
                    break
        except Exception:
            target = None

        try:
            if target is None:
                new_msg = await panel_channel.send(embed=embed, view=view)
                try:
                    await new_msg.pin()
                except Exception:
                    pass
                return True

            await target.edit(embed=embed, view=view)
            return False
        except Exception:
            return False

    async def _sync_guild_bank_views(self, guild: discord.Guild):
        bank_cog = self.bot.get_cog("GuildBankCog")
        if bank_cog is None or not hasattr(bank_cog, "_update_bank_panel"):
            return
        try:
            await bank_cog._update_bank_panel(guild)
        except Exception:
            logging.exception("Failed to sync guild bank views during setup")

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        await self.run_setup(guild)

    async def run_setup(self, guild: discord.Guild, interaction=None):
        logging.info(f"Running DKP setup for guild: {guild.name} ({guild.id})")

        bot_member = guild.me
        if bot_member is None and getattr(self.bot, "user", None) is not None:
            bot_member = guild.get_member(self.bot.user.id)
        if bot_member is None and getattr(self.bot, "user", None) is not None:
            try:
                bot_member = await guild.fetch_member(self.bot.user.id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                bot_member = None

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=True,
                read_message_history=True,
                send_messages=False,
            )
        }
        if bot_member is not None:
            overwrites[bot_member] = discord.PermissionOverwrite(
                view_channel=True,
                read_message_history=True,
                send_messages=True,
                manage_messages=True,
                manage_channels=True,
            )

        def _is_category_channel(ch) -> bool:
            return isinstance(ch, discord.CategoryChannel) or (
                ch is not None and hasattr(ch, "create_text_channel") and hasattr(ch, "text_channels")
            )

        def _is_text_channel(ch) -> bool:
            return isinstance(ch, discord.TextChannel) or (ch is not None and hasattr(ch, "send"))

        # Check if setup has already been run
        config = await self.bot.db.get_guild_config(guild.id)
        if config and config['dkp_category_id']:
            category = guild.get_channel(config['dkp_category_id'])
            if _is_category_channel(category):
                if bot_member is not None:
                    try:
                        await category.set_permissions(
                            bot_member,
                            read_messages=True,
                            send_messages=True,
                            manage_messages=True,
                        )
                        await category.set_permissions(
                            guild.default_role,
                            read_messages=True,
                            send_messages=False,
                        )
                    except discord.Forbidden:
                        pass
                    except Exception:
                        pass

                try:
                    existing_active_named = None
                    for ch in guild.categories:
                        if (ch.name or "").lower() == "dkp-active-raids":
                            existing_active_named = ch
                            break
                    if category.name != "DKP-active-raids" and (existing_active_named is None or existing_active_named.id == category.id):
                        await category.edit(name="DKP-active-raids")
                except Exception:
                    pass

                # We have a config row and a DKP category, but older installs may be missing
                # the raid channel ID or the channel may have been deleted. In that case,
                # attempt a lightweight repair instead of bailing out.
                raid_channel_id = config['raid_channel_id'] if 'raid_channel_id' in config.keys() else None
                raid_channel = guild.get_channel(raid_channel_id) if raid_channel_id else None

                changed = False

                admin_role_id = config['admin_role_id'] if 'admin_role_id' in config.keys() else None
                admin_role = guild.get_role(admin_role_id) if admin_role_id else None
                if admin_role is None:
                    try:
                        admin_role = discord.utils.get(guild.roles, name="DKP Admin")
                        if admin_role is None:
                            admin_role = await guild.create_role(
                                name="DKP Admin",
                                permissions=discord.Permissions.none(),
                                hoist=True,
                                mentionable=True,
                            )
                        await self.bot.db.execute(
                            "UPDATE guilds SET admin_role_id = ? WHERE guild_id = ?",
                            (admin_role.id, guild.id),
                        )
                        changed = True
                    except discord.Forbidden:
                        pass
                    except Exception:
                        pass

                if not raid_channel:
                    # Try to locate an existing "active-raids" channel under the DKP category,
                    # or create it if it does not exist.
                    raid_channel = None
                    for channel in category.text_channels:
                        if channel.name == "active-raids":
                            raid_channel = channel
                            break

                    if not raid_channel:
                        raid_channel = await category.create_text_channel("active-raids")

                    await self.bot.db.execute(
                        "UPDATE guilds SET raid_channel_id = ? WHERE guild_id = ?",
                        (raid_channel.id, guild.id),
                    )
                    changed = True
                    msg = f"Setup repaired for {guild.name}: raid channel linked."
                    logging.info(msg)
                else:
                    msg = f"Setup already exists for {guild.name}."
                    logging.warning(f"Bot re-joined {guild.name}, setup already exists.")

                archive_category_id = config['archive_category_id'] if 'archive_category_id' in config.keys() else None
                archive_category = guild.get_channel(archive_category_id) if archive_category_id else None
                if not _is_category_channel(archive_category):
                    archive_category = None
                    for ch in guild.categories:
                        if (ch.name or "").lower() == "dkp-archive":
                            archive_category = ch
                            break
                    if archive_category is None:
                        archive_category = await guild.create_category("DKP-archive", overwrites=overwrites)
                    await self.bot.db.execute(
                        "UPDATE guilds SET archive_category_id = ? WHERE guild_id = ?",
                        (archive_category.id, guild.id),
                    )
                    changed = True
                elif bot_member is not None:
                    try:
                        await archive_category.set_permissions(
                            bot_member,
                            read_messages=True,
                            send_messages=True,
                            manage_messages=True,
                        )
                        await archive_category.set_permissions(
                            guild.default_role,
                            read_messages=True,
                            send_messages=False,
                        )
                    except discord.Forbidden:
                        pass
                    except Exception:
                        pass

                completed_raid_channel_id = (
                    config['completed_raid_channel_id']
                    if 'completed_raid_channel_id' in config.keys()
                    else None
                )
                completed_raid_channel = (
                    guild.get_channel(completed_raid_channel_id)
                    if completed_raid_channel_id
                    else None
                )
                if not _is_text_channel(completed_raid_channel):
                    completed_raid_channel = None
                    for ch in guild.text_channels:
                        if (ch.name or "").lower() == "completed-raids":
                            completed_raid_channel = ch
                            break

                if _is_text_channel(completed_raid_channel) and _is_category_channel(archive_category):
                    if completed_raid_channel.category_id != archive_category.id:
                        try:
                            await completed_raid_channel.edit(category=archive_category)
                        except Exception:
                            pass

                if not _is_text_channel(completed_raid_channel):
                    if _is_category_channel(archive_category):
                        completed_raid_channel = await archive_category.create_text_channel("completed-raids")

                if _is_text_channel(completed_raid_channel):
                    await self.bot.db.execute(
                        "UPDATE guilds SET completed_raid_channel_id = ? WHERE guild_id = ?",
                        (completed_raid_channel.id, guild.id),
                    )
                    changed = True

                dkp_channel_id = config['dkp_channel_id'] if 'dkp_channel_id' in config.keys() else None
                dkp_channel_obj = guild.get_channel(dkp_channel_id) if dkp_channel_id else None
                auction_changed = await self._ensure_auction_channels(guild, config, archive_category, dkp_channel_obj)
                if auction_changed:
                    changed = True

                (
                    _bank_category,
                    guild_bank_channel,
                    inventory_channel,
                    transactions_channel,
                    bank_changed,
                ) = await self._ensure_guild_bank_channels(
                    guild,
                    config,
                    overwrites,
                    dkp_category=category,
                )
                if bank_changed:
                    changed = True

                panel_changed = await self._ensure_guild_bank_panel_message(
                    guild_bank_channel,
                    inventory_channel,
                    transactions_channel,
                )
                if panel_changed:
                    changed = True

                await self._sync_guild_bank_views(guild)

                if changed and msg.startswith("Setup already exists"):
                    msg = f"Setup repaired for {guild.name}."

                if interaction:
                    # followup.send is used because we deferred the response
                    try:
                        await interaction.followup.send(msg, ephemeral=True)
                    except (discord.NotFound, discord.HTTPException):
                        logging.warning("Setup finished but interaction is no longer valid.")
                return
        # Create a DKP category
        try:
            category = None
            for ch in guild.categories:
                if (ch.name or "").lower() == "dkp-active-raids":
                    category = ch
                    break
            if category is None:
                category = await guild.create_category("DKP-active-raids", overwrites=overwrites)
            else:
                if bot_member is not None:
                    try:
                        await category.set_permissions(
                            bot_member,
                            read_messages=True,
                            send_messages=True,
                            manage_messages=True,
                        )
                    except discord.Forbidden:
                        pass
                    except Exception:
                        pass

                if category.overwrites_for(guild.default_role).send_messages is not False:
                    try:
                        await category.set_permissions(
                            guild.default_role,
                            read_messages=True,
                            send_messages=False,
                        )
                    except discord.Forbidden:
                        pass
                    except Exception:
                        pass

            # Create text channels
            dkp_channel = None
            raid_channel = None
            for channel in category.text_channels:
                if (channel.name or "").lower() == "dkp-system":
                    dkp_channel = channel
                elif (channel.name or "").lower() == "active-raids":
                    raid_channel = channel

            if dkp_channel is None:
                dkp_channel = await category.create_text_channel("dkp-system")
            if raid_channel is None:
                raid_channel = await category.create_text_channel("active-raids")

            archive_category = None
            for ch in guild.categories:
                if (ch.name or "").lower() == "dkp-archive":
                    archive_category = ch
                    break
            if archive_category is None:
                archive_category = await guild.create_category("DKP-archive", overwrites=overwrites)
            elif bot_member is not None:
                try:
                    await archive_category.set_permissions(
                        bot_member,
                        read_messages=True,
                        send_messages=True,
                        manage_messages=True,
                    )
                    await archive_category.set_permissions(
                        guild.default_role,
                        read_messages=True,
                        send_messages=False,
                    )
                except discord.Forbidden:
                    pass
                except Exception:
                    pass

            completed_raid_channel = None
            completed_auctions_channel = None
            for channel in archive_category.text_channels:
                if (channel.name or "").lower() == "completed-raids":
                    completed_raid_channel = channel
                elif (channel.name or "").lower() == "completed-auctions":
                    completed_auctions_channel = channel
            if completed_raid_channel is None:
                completed_raid_channel = await archive_category.create_text_channel("completed-raids")
            if completed_auctions_channel is None:
                completed_auctions_channel = await archive_category.create_text_channel("completed-auctions")

            # Explicitly clean up any legacy "Raid-Template" voice channel under this category.
            # Older versions of the bot created a template VC; the current design does not use it.
            for channel in list(category.voice_channels):
                if channel.name.lower() == "raid-template":
                    try:
                        await channel.delete(reason="Remove legacy Raid-Template voice channel")
                    except discord.Forbidden:
                        logging.warning("Failed to delete legacy Raid-Template voice channel due to permissions.")
                    except Exception as e:
                        logging.warning(f"Error deleting legacy Raid-Template voice channel: {e}")

            # (Legacy) Raid voice channel template is no longer used; store NULL for compatibility.
            vc_template_id = None

            (
                guild_bank_category,
                guild_bank_channel,
                guild_bank_inventory_channel,
                guild_bank_transactions_channel,
                _,
            ) = await self._ensure_guild_bank_channels(
                guild,
                None,
                overwrites,
                dkp_category=category,
            )

            # Create or reuse roles
            admin_role = discord.utils.get(guild.roles, name="DKP Admin")
            if admin_role is None:
                admin_role = await guild.create_role(
                    name="DKP Admin",
                    permissions=discord.Permissions.none(),
                    hoist=True,
                    mentionable=True,
                )

            officer_role = discord.utils.get(guild.roles, name="Officer")
            if officer_role is None:
                officer_role = await guild.create_role(
                    name="Officer",
                    permissions=discord.Permissions.none(),
                    hoist=True,
                    mentionable=True,
                )

            raider_role = discord.utils.get(guild.roles, name="Raider")
            if raider_role is None:
                raider_role = await guild.create_role(
                    name="Raider",
                    permissions=discord.Permissions.none(),
                    hoist=True,
                    mentionable=True,
                )

            raid_leader_role = discord.utils.get(guild.roles, name="Raid-Leader")
            if raid_leader_role is None:
                raid_leader_role = await guild.create_role(
                    name="Raid-Leader",
                    permissions=discord.Permissions.none(),
                    hoist=True,
                    mentionable=True,
                )

            # Save to DB
            await self.bot.db.execute(
                "INSERT OR REPLACE INTO guilds (guild_id, dkp_category_id, archive_category_id, dkp_channel_id, raid_channel_id, completed_raid_channel_id, completed_auctions_channel_id, raid_vc_template_id, admin_role_id, officer_role_id, raider_role_id, raid_leader_role_id, guild_bank_category_id, guild_bank_channel_id, guild_bank_inventory_channel_id, guild_bank_transactions_channel_id, license_key) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    guild.id,
                    category.id,
                    archive_category.id,
                    dkp_channel.id,
                    raid_channel.id,
                    completed_raid_channel.id,
                    completed_auctions_channel.id,
                    vc_template_id,
                    admin_role.id,
                    officer_role.id,
                    raider_role.id,
                    raid_leader_role.id,
                    guild_bank_category.id,
                    guild_bank_channel.id,
                    guild_bank_inventory_channel.id,
                    guild_bank_transactions_channel.id,
                    self.bot.license_key,
                )
            )
            # Send welcome panel
            embed = create_info_embed(
                "Welcome to the DKP Bot!",
                "This bot helps you manage your guild's Dragon Kill Points system right here in Discord.\n\n"
                "**Button:**\n"
                "\t **Open DKP Panel:** Opens a private (ephemeral) control panel with the actions you have access to."
            )
            view = WelcomeView(self.bot)
            message = await dkp_channel.send(embed=embed, view=view)
            await message.pin()

            auction_embed = create_info_embed(
                "💎 Community Auctions",
                "Click the button below to open the Auction Panel. "
                "Officers can start and end auctions; all guild members can place bids.",
            )
            auction_view = AuctionControlPanelView(self.bot)
            try:
                auction_msg = await dkp_channel.send(embed=auction_embed, view=auction_view)
                await self.bot.db.execute(
                    "UPDATE guilds SET auction_panel_message_id = ? WHERE guild_id = ?",
                    (auction_msg.id, guild.id),
                )
            except Exception:
                logging.exception("Failed to send auction panel message during setup")

            await self._ensure_guild_bank_panel_message(
                guild_bank_channel,
                guild_bank_inventory_channel,
                guild_bank_transactions_channel,
            )
            await self._sync_guild_bank_views(guild)

            logging.info(f"Successfully set up DKP system for guild {guild.name}")
            if interaction:
                try:
                    await interaction.followup.send("DKP system setup complete!", ephemeral=True)
                except (discord.NotFound, discord.HTTPException):
                    logging.warning("Setup complete but interaction is no longer valid.")
        except discord.Forbidden:
            logging.exception(f"Missing permissions to set up channels or roles in {guild.name}")
            # Try to send a message to the owner or the first available channel
            try:
                await guild.owner.send(
                    "I tried to set up my channels and roles in your server but I'm missing required permissions. "
                    "Please ensure I have at least: 'Manage Channels', 'Manage Roles', and permission to 'View Channels' and 'Send Messages' "
                    "in the DKP channels/categories, then re-invite me."
                )
            except discord.Forbidden:
                pass # Can't do anything else
            if interaction:
                try:
                    await interaction.followup.send(
                        "Missing permissions to complete setup. Please grant 'Manage Channels', 'Manage Roles', and ensure I can 'View Channels' and 'Send Messages' in the DKP channels/categories, then try again.",
                        ephemeral=True,
                    )
                except (discord.NotFound, discord.HTTPException):
                    logging.warning("Setup permissions error but interaction is no longer valid.")

    @app_commands.command(name="setup_dkp", description="Manually (re)run the DKP system setup. Admins only.")
    @app_commands.check(is_admin)
    async def setup_dkp(self, interaction: discord.Interaction):
        """Manually (re)run the DKP system setup."""
        if interaction.guild is None:
            return await interaction.response.send_message("This command cannot be used in DMs.", ephemeral=True)
        # We need to defer here because the setup can take a moment
        try:
            await interaction.response.defer(ephemeral=True)
        except (discord.NotFound, discord.HTTPException):
            return
        await self.run_setup(interaction.guild, interaction=interaction)

    @app_commands.command(
        name="refresh_welcome",
        description="Refresh the pinned DKP welcome panel message (updates buttons). Admins only.",
    )
    @app_commands.check(is_admin)
    async def refresh_welcome(self, interaction: discord.Interaction):
        if interaction.guild is None:
            return await interaction.response.send_message("This command cannot be used in DMs.", ephemeral=True)

        try:
            await interaction.response.defer(ephemeral=True)
        except (discord.NotFound, discord.HTTPException):
            return

        config = await self.bot.db.get_guild_config(interaction.guild.id)
        dkp_channel_id = None
        if config and ("dkp_channel_id" in getattr(config, "keys", lambda: [])()):
            dkp_channel_id = config["dkp_channel_id"]

        if not dkp_channel_id:
            return await interaction.followup.send(
                "DKP system is not set up yet. Run `/setup_dkp` first.",
                ephemeral=True,
            )

        channel = interaction.guild.get_channel(int(dkp_channel_id))
        if channel is None:
            try:
                channel = await interaction.guild.fetch_channel(int(dkp_channel_id))
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                channel = None

        if channel is None or not hasattr(channel, "send"):
            return await interaction.followup.send(
                "Couldn't find the DKP system channel. Try re-running `/setup_dkp`.",
                ephemeral=True,
            )

        embed = create_info_embed(
            "Welcome to the DKP Bot!",
            "This bot helps you manage your guild's Dragon Kill Points system right here in Discord.\n\n"
            "**Button:**\n"
            "\t **Open DKP Panel:** Opens a private (ephemeral) control panel with the actions you have access to.",
        )
        view = WelcomeView(self.bot)

        target = None
        try:
            pins = await channel.pins()
        except Exception:
            pins = []

        for msg in list(pins or []):
            try:
                if self.bot.user is None:
                    continue
                if msg.author is None or msg.author.id != self.bot.user.id:
                    continue
                for emb in list(getattr(msg, "embeds", []) or []):
                    if (getattr(emb, "title", None) or "").strip() == "Welcome to the DKP Bot!":
                        target = msg
                        break
                if target:
                    break
            except Exception:
                continue

        try:
            if target is not None:
                await target.edit(embed=embed, view=view)
                msg = target
            else:
                msg = await channel.send(embed=embed, view=view)
                try:
                    await msg.pin()
                except Exception:
                    pass
        except discord.Forbidden:
            return await interaction.followup.send(
                "I don't have permission to post or edit the welcome panel in that channel.",
                ephemeral=True,
            )
        except Exception:
            logging.exception("Failed to refresh welcome panel")
            return await interaction.followup.send(
                "Failed to refresh the welcome panel. Check logs.",
                ephemeral=True,
            )

        return await interaction.followup.send(
            f"Welcome panel refreshed: {getattr(msg, 'jump_url', '')}",
            ephemeral=True,
        )

    @app_commands.command(
        name="refresh_auction_panel",
        description="Re-post or repair the Auction Panel message in dkp-system. Admins only.",
    )
    @app_commands.check(is_admin)
    async def refresh_auction_panel(self, interaction: discord.Interaction):
        if interaction.guild is None:
            return await interaction.response.send_message("This command cannot be used in DMs.", ephemeral=True)

        try:
            await interaction.response.defer(ephemeral=True)
        except (discord.NotFound, discord.HTTPException):
            return

        config = await self.bot.db.get_guild_config(interaction.guild.id)
        dkp_channel_id = config["dkp_channel_id"] if config and "dkp_channel_id" in getattr(config, "keys", lambda: [])() else None

        if not dkp_channel_id:
            return await interaction.followup.send(
                "DKP system is not set up yet. Run `/setup_dkp` first.", ephemeral=True
            )

        channel = interaction.guild.get_channel(int(dkp_channel_id))
        if channel is None:
            try:
                channel = await interaction.guild.fetch_channel(int(dkp_channel_id))
            except Exception:
                channel = None

        if channel is None or not hasattr(channel, "send"):
            return await interaction.followup.send(
                "Couldn't find the DKP system channel. Try re-running `/setup_dkp`.", ephemeral=True
            )

        archive_category_id = config["archive_category_id"] if config and "archive_category_id" in getattr(config, "keys", lambda: [])() else None
        archive_category = interaction.guild.get_channel(archive_category_id) if archive_category_id else None

        auction_changed = await self._ensure_auction_channels(interaction.guild, config, archive_category, channel)
        await interaction.followup.send(
            "Auction panel refreshed." if auction_changed else "Auction panel is already up to date.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(SetupCog(bot))
