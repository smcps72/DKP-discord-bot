import datetime
import logging
import uuid

import discord
from discord.ext import commands

from ..ui.views import AuctionBidView, AuctionOpenPanelView, RaidPopupView
from ..utils import create_info_embed, create_error_embed, create_success_embed, send_dkp_change_dm

logger = logging.getLogger(__name__)

class AuctionCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _get_interaction_context(self, interaction: discord.Interaction):
        guild = getattr(interaction, "guild", None)
        channel = getattr(interaction, "channel", None)
        user = getattr(interaction, "user", None)
        return {
            "guild_id": getattr(guild, "id", None),
            "channel_id": getattr(channel, "id", None),
            "user_id": getattr(user, "id", None),
        }

    def _log_step(self, interaction: discord.Interaction, trace_id: str, step: str, **extra):
        ctx = self._get_interaction_context(interaction)
        payload = {
            "trace_id": trace_id,
            "step": step,
        }
        payload.update(ctx)
        payload.update(extra)
        logger.info(
            "auction_flow %s",
            " ".join(f"{k}={v}" for k, v in payload.items()),
        )

    async def process_auction_start(
        self,
        interaction: discord.Interaction,
        item_name: str,
        trace_id: str | None = None,
        *,
        source: str | None = None,
        guild_id: int | None = None,
        popup_can_manage: bool = False,
        popup_can_rename_thread: bool = False,
        popup_message: discord.Message | None = None,
    ):
        async def respond_popup(message: str, *, title: str = "Auction"):
            embed = create_info_embed(title, message)
            popup_view = RaidPopupView(
                self.bot,
                mode=("manage" if popup_can_manage else "main"),
                can_manage=popup_can_manage,
                can_rename_thread=popup_can_rename_thread,
            )
            try:
                await interaction.edit_original_response(embed=embed, view=popup_view)
            except Exception:
                try:
                    await interaction.followup.send(embed=embed, view=popup_view, ephemeral=True)
                except Exception:
                    pass

        async def send_error(message: str):
            if source in ("raid_popup",):
                await respond_popup(message, title="Error")
            else:
                try:
                    await interaction.followup.send(
                        embed=create_error_embed("Error", message), ephemeral=True
                    )
                except Exception:
                    pass

        item_name = (item_name or "").strip()
        if not item_name:
            item_name = "Item"
        if len(item_name) > 100:
            item_name = item_name[:100]
        if trace_id is None:
            trace_id = str(uuid.uuid4())
        self._log_step(interaction, trace_id, "auction_start.begin", item_name=item_name, source=source)

        if not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=True)
            except Exception:
                pass

        resolved_guild_id = guild_id
        standalone = resolved_guild_id is not None and source not in ("raid_popup",)

        if standalone:
            active_auction = await self.bot.db.get_active_guild_auction(resolved_guild_id)
            if active_auction:
                self._log_step(interaction, trace_id, "auction_start.already_active", guild_id=resolved_guild_id)
                return await send_error("An auction is already in progress.")

            auction_id = await self.bot.db.execute_insert(
                "INSERT INTO auctions (guild_id, item_name) VALUES (?, ?)",
                (resolved_guild_id, item_name),
            )
            self._log_step(interaction, trace_id, "auction_start.created_standalone", auction_id=auction_id, guild_id=resolved_guild_id)
        else:
            channel = getattr(interaction, "channel", None)
            raid = await self.bot.db.get_raid_by_thread(channel.id) if channel else None
            if not raid:
                self._log_step(interaction, trace_id, "auction_start.raid_missing")
                return await send_error("This is not an active raid thread.")

            resolved_guild_id = raid.get("guild_id") if isinstance(raid, dict) else getattr(raid, "guild_id", None)

            active_auction = await self.bot.db.get_active_auction(raid['id'])
            if active_auction:
                existing_id = active_auction.get("id") if isinstance(active_auction, dict) else None
                self._log_step(interaction, trace_id, "auction_start.already_active", auction_id=existing_id, raid_id=raid['id'])
                return await send_error("An auction is already in progress for this raid.")

            participant_ids: set[int] = set()
            vc = interaction.guild.get_channel(raid['vc_id']) if interaction.guild else None
            for m in getattr(vc, "members", []):
                if not getattr(m, "bot", False):
                    participant_ids.add(m.id)
            try:
                member_rows = await self.bot.db.get_raid_members(raid['id'])
            except Exception:
                member_rows = []
            for row in member_rows:
                try:
                    uid = int(row["user_id"])
                except (KeyError, TypeError, ValueError):
                    continue
                participant_ids.add(uid)

            if not participant_ids:
                self._log_step(interaction, trace_id, "auction_start.vc_empty")
                return await send_error("No raid participants found. Cannot start auction.")

            auction_id = await self.bot.db.execute_insert(
                "INSERT INTO auctions (guild_id, raid_id, item_name) VALUES (?, ?, ?)",
                (resolved_guild_id, raid['id'], item_name),
            )
            self._log_step(interaction, trace_id, "auction_start.created", auction_id=auction_id, raid_id=raid['id'])

        embed = create_info_embed(
            f"💎 Auction Started: {item_name}",
            "Bidding is now open!\n\n"
            "Click **Open Bid Panel** below to get a private (ephemeral) bidding panel."
        )
        panel_view = AuctionOpenPanelView(self.bot)
        channel = getattr(interaction, "channel", None)
        msg = None
        if channel is not None:
            try:
                msg = await channel.send(embed=embed, view=panel_view)
                self._log_step(interaction, trace_id, "auction_start.panel_sent", message_id=msg.id)
            except Exception:
                logging.exception("Failed to send auction panel message")

        if source in ("raid_popup",):
            await respond_popup("Auction started.", title="Start Auction")
        else:
            try:
                await interaction.followup.send(
                    embed=create_success_embed("Auction Started", f"Auction for **{item_name}** is now open!"),
                    ephemeral=True,
                )
            except Exception:
                logging.exception("Failed to send followup in auction start")

        if msg is not None:
            try:
                await self.bot.db.execute(
                    "UPDATE auctions SET message_id = ? WHERE id = ?",
                    (msg.id, auction_id),
                )
            except Exception:
                logging.exception("Failed to store auction message_id")

    async def send_bid_panel(self, interaction: discord.Interaction, auction_id: int, trace_id: str | None = None):
        if trace_id is None:
            trace_id = str(uuid.uuid4())
        self._log_step(interaction, trace_id, "send_bid_panel.begin", auction_id=auction_id)
        # LEFT JOIN raids so standalone auctions (raid_id IS NULL) still work.
        auction_details_query = """
            SELECT a.*, COALESCE(r.guild_id, a.guild_id) AS guild_id, r.thread_id
            FROM auctions a
            LEFT JOIN raids r ON a.raid_id = r.id
            WHERE a.id = ? AND a.is_active = 1
        """
        auction = await self.bot.db.fetchone(auction_details_query, (auction_id,))
        if not auction:
            self._log_step(interaction, trace_id, "send_bid_panel.auction_missing", auction_id=auction_id)
            if not interaction.response.is_done():
                return await interaction.response.send_message("This auction has ended.", ephemeral=True)
            return await interaction.followup.send("This auction has ended.", ephemeral=True)

        guild_id = auction["guild_id"]
        user_dkp = await self.bot.db.get_user_dkp(interaction.user.id, guild_id)
        self._log_step(interaction, trace_id, "send_bid_panel.user_dkp_loaded", guild_id=guild_id, user_dkp=user_dkp)

        desc = (
            f"Your DKP: **{user_dkp}**\n\n"
            "Use **Bid** to place your single secret bid for this item. "
            "You can bid any positive amount up to your available DKP; only your first bid counts."
        )
        embed = create_info_embed(f"Bid on: {auction['item_name']}", desc)
        view = AuctionBidView(self.bot, auction_id)

        if not interaction.response.is_done():
            self._log_step(interaction, trace_id, "send_bid_panel.send_initial_response", auction_id=auction_id)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        else:
            self._log_step(interaction, trace_id, "send_bid_panel.send_followup_response", auction_id=auction_id)
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

        raid_cog = self.bot.get_cog("RaidCog")
        if raid_cog:
            try:
                await raid_cog.maybe_send_control_panel_ephemeral(interaction)
            except Exception:
                logging.exception("Failed to re-show control panel after bid panel")

    async def process_bid(self, interaction: discord.Interaction, auction_id: int, bid_amount_str: str, trace_id: str | None = None):
        if trace_id is None:
            trace_id = str(uuid.uuid4())
        self._log_step(interaction, trace_id, "bid.begin", auction_id=auction_id, bid_amount_raw=bid_amount_str)
        try:
            bid_amount = int(bid_amount_str)
            if bid_amount <= 0:
                raise ValueError
        except ValueError:
            self._log_step(interaction, trace_id, "bid.invalid_amount", auction_id=auction_id)
            return await interaction.response.send_message("Bid must be a positive number.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        # LEFT JOIN raids so standalone auctions (raid_id IS NULL) still work.
        auction_details_query = """
            SELECT a.*, COALESCE(r.guild_id, a.guild_id) AS guild_id, r.thread_id
            FROM auctions a
            LEFT JOIN raids r ON a.raid_id = r.id
            WHERE a.id = ? AND a.is_active = 1
        """
        auction = await self.bot.db.fetchone(auction_details_query, (auction_id,))

        if not auction:
            self._log_step(interaction, trace_id, "bid.auction_missing", auction_id=auction_id)
            return await interaction.followup.send("This auction has ended.", ephemeral=True)

        guild_id = auction["guild_id"]
        user_dkp = await self.bot.db.get_user_dkp(interaction.user.id, guild_id)

        if bid_amount > user_dkp:
            self._log_step(interaction, trace_id, "bid.exceeds_dkp", bid_amount=bid_amount, user_dkp=user_dkp)
            await interaction.followup.send(
                f"Your bid of **{bid_amount}** exceeds your available DKP of **{user_dkp}**.",
                ephemeral=True,
            )

            raid_cog = self.bot.get_cog("RaidCog")
            if raid_cog:
                try:
                    await raid_cog.maybe_send_control_panel_ephemeral(interaction)
                except Exception:
                    logging.exception("Failed to re-show control panel after bid validation")
            return

        # Enforce a single bid per user per auction.
        existing_bid = await self.bot.db.get_user_auction_bid(auction_id, interaction.user.id)
        if existing_bid is not None:
            self._log_step(interaction, trace_id, "bid.already_exists", auction_id=auction_id)
            await interaction.followup.send(
                embed=create_success_embed(
                    "Bid Already Placed",
                    "You have already placed a bid for this auction. "
                    "Only your first bid counts.",
                ),
                ephemeral=True,
            )

            raid_cog = self.bot.get_cog("RaidCog")
            if raid_cog:
                try:
                    await raid_cog.maybe_send_control_panel_ephemeral(interaction)
                except Exception:
                    logging.exception("Failed to re-show control panel after bid recording")
            return

        # Record the user's single bid without revealing any information about
        # other bidders or bid ordering.
        await self.bot.db.record_auction_bid(auction_id, interaction.user.id, bid_amount)
        self._log_step(interaction, trace_id, "bid.recorded", auction_id=auction_id, bid_amount=bid_amount)

        await interaction.followup.send(
            embed=create_success_embed(
                "Bid Submitted",
                f"Your bid of **{bid_amount} DKP** for **{auction['item_name']}** has been received.",
            ),
            ephemeral=True,
        )
        self._log_step(interaction, trace_id, "bid.confirmation_sent", auction_id=auction_id, bid_amount=bid_amount)

        raid_cog = self.bot.get_cog("RaidCog")
        if raid_cog:
            try:
                await raid_cog.maybe_send_control_panel_ephemeral(interaction)
            except Exception:
                logging.exception("Failed to re-show control panel after auction end")

    async def _post_completed_auction_archive(self, guild: discord.Guild, auction: dict, winner_name: str, winning_amount: int, total_bids: int):
        """Post a result message to the completed-auctions channel and update the pinned index."""
        try:
            guild_config = await self.bot.db.get_guild_config(guild.id)
            if not guild_config:
                return
            try:
                channel_id = guild_config["completed_auctions_channel_id"]
            except (KeyError, TypeError, IndexError):
                channel_id = None
            if not channel_id:
                return
            channel = guild.get_channel(channel_id)
            if channel is None:
                return

            now = datetime.datetime.now(datetime.timezone.utc)
            timestamp_str = discord.utils.format_dt(now, style="f")

            result_embed = create_success_embed(
                f"Auction Completed: {auction['item_name']}",
                f"**Winner:** {winner_name}\n"
                f"**Winning Bid:** {winning_amount} DKP\n"
                f"**Total Bids:** {total_bids}\n"
                f"**Ended:** {timestamp_str}",
            )
            await channel.send(embed=result_embed)

            pinned = await channel.pins()
            index_msg = None
            for p in pinned:
                if guild.me and p.author.id == guild.me.id and p.embeds and "Auction History" in (p.embeds[0].title or ""):
                    index_msg = p
                    break

            entry_line = f"`{now.strftime('%Y-%m-%d')}` — **{auction['item_name']}** → {winner_name} ({winning_amount} DKP)"

            if index_msg is not None:
                existing = index_msg.embeds[0].description or ""
                lines = [l for l in existing.split("\n") if l.strip()][-19:]
                lines.append(entry_line)
                updated_desc = "\n".join(lines)
                updated_embed = create_info_embed("📜 Auction History", updated_desc)
                await index_msg.edit(embed=updated_embed)
            else:
                index_embed = create_info_embed("📜 Auction History", entry_line)
                new_index = await channel.send(embed=index_embed)
                try:
                    await new_index.pin()
                except Exception:
                    pass
        except Exception:
            logging.exception("Failed to post completed auction to archive")

    async def end_auction_from_button(
        self,
        interaction: discord.Interaction,
        *,
        source: str | None = None,
        guild_id: int | None = None,
        popup_can_manage: bool = False,
        popup_can_rename_thread: bool = False,
        popup_message: discord.Message | None = None,
    ):
        async def respond_popup(message: str, *, title: str = "End Auction"):
            embed = create_info_embed(title, message)
            popup_view = RaidPopupView(
                self.bot,
                mode=("manage" if popup_can_manage else "main"),
                can_manage=popup_can_manage,
                can_rename_thread=popup_can_rename_thread,
            )
            try:
                await interaction.edit_original_response(embed=embed, view=popup_view)
            except Exception:
                try:
                    await interaction.followup.send(embed=embed, view=popup_view, ephemeral=True)
                except Exception:
                    pass

        async def send_error(message: str):
            if source in ("raid_popup",):
                await respond_popup(message, title="Error")
            else:
                try:
                    await interaction.followup.send(
                        embed=create_error_embed("Error", message), ephemeral=True
                    )
                except Exception:
                    pass

        trace_id = str(uuid.uuid4())
        self._log_step(interaction, trace_id, "end_auction.begin", source=source)

        resolved_guild_id = guild_id or (interaction.guild.id if interaction.guild else None)

        channel = getattr(interaction, "channel", None)
        auction = None
        if channel is not None:
            raid = await self.bot.db.get_raid_by_thread(channel.id)
            if raid:
                auction = await self.bot.db.get_active_auction(raid['id'])
        if auction is None and resolved_guild_id:
            auction = await self.bot.db.get_active_guild_auction(resolved_guild_id)

        if not auction:
            self._log_step(interaction, trace_id, "end_auction.no_active_auction")
            return await send_error("There is no active auction to end.")

        rows_affected = await self.bot.db.execute_rowcount(
            "UPDATE auctions SET is_active = 0, ended_at = CURRENT_TIMESTAMP WHERE id = ? AND is_active = 1",
            (auction['id'],),
        )
        if rows_affected == 0:
            self._log_step(interaction, trace_id, "end_auction.race_lost", auction_id=auction['id'])
            return await send_error("The auction was just ended by someone else.")

        bids = await self.bot.db.fetchall(
            "SELECT user_id, amount, created_at FROM auction_bids WHERE auction_id = ?",
            (auction["id"],),
        )

        if not bids:
            self._log_step(interaction, trace_id, "end_auction.no_bids", auction_id=auction["id"])
            no_bids_msg = f"The auction for **{auction['item_name']}** has ended with no bids."
            if channel is not None:
                try:
                    await channel.send(embed=create_info_embed("Auction Ended", no_bids_msg))
                except Exception:
                    pass
            if source in ("raid_popup",):
                await respond_popup(no_bids_msg, title="Auction Ended")
            else:
                try:
                    await interaction.followup.send(
                        embed=create_info_embed("Auction Ended", no_bids_msg), ephemeral=True
                    )
                except Exception:
                    pass
            return

        bids_sorted = sorted(
            bids,
            key=lambda row: (-int(row["amount"]), row["created_at"]),
        )
        winning_bid = bids_sorted[0]
        winning_user_id = winning_bid["user_id"]
        winning_amount = int(winning_bid["amount"])
        self._log_step(interaction, trace_id, "end_auction.winner_selected", auction_id=auction["id"], winning_user_id=winning_user_id, winning_amount=winning_amount)

        guild = interaction.guild
        winner = guild.get_member(winning_user_id) if guild else None
        winner_name = winner.mention if winner else f"User ID: {winning_user_id}"

        if resolved_guild_id is None and guild:
            resolved_guild_id = guild.id

        await self.bot.db.modify_user_dkp(
            winning_user_id,
            resolved_guild_id,
            -winning_amount,
            f"Won auction for {auction['item_name']}",
            username=winner.display_name if winner else None,
        )

        if winner is not None and guild is not None:
            new_total = None
            try:
                new_total = await self.bot.db.get_user_dkp(winning_user_id, guild.id)
            except Exception:
                new_total = None
            await send_dkp_change_dm(
                winner,
                guild,
                -winning_amount,
                f"Won auction for {auction['item_name']}",
                new_total=new_total,
            )

        result_embed = create_success_embed(
            f"Auction Concluded: {auction['item_name']}",
            f"Congratulations to {winner_name} for winning with a bid of **{winning_amount} DKP**!",
        )
        if channel is not None:
            try:
                await channel.send(embed=result_embed)
            except Exception:
                pass
        self._log_step(interaction, trace_id, "end_auction.completed", auction_id=auction["id"])

        if source in ("raid_popup",):
            await respond_popup(
                f"Ended auction for **{auction['item_name']}**. Winner: {winner_name} (**{winning_amount} DKP**).",
                title="End Auction",
            )
        else:
            try:
                await interaction.followup.send(
                    embed=create_success_embed(
                        "Auction Ended",
                        f"Winner: {winner_name} — **{winning_amount} DKP** for **{auction['item_name']}**.",
                    ),
                    ephemeral=True,
                )
            except Exception:
                pass

        if guild:
            await self._post_completed_auction_archive(
                guild, dict(auction), winner_name, winning_amount, len(bids)
            )


async def setup(bot):
    await bot.add_cog(AuctionCog(bot))
