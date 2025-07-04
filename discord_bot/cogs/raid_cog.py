import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime
import logging
from ..utils import create_info_embed, create_error_embed, create_success_embed, is_officer
from ..ui.views import RaidControlView

class RaidCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def create_raid_from_interaction(self, interaction: discord.Interaction):
        # Defer the response if it hasn't been done yet. 
        # This makes the function safe to call from commands or views.
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)

        if not await is_officer(interaction):
            return await interaction.followup.send("You must be an officer to create a raid.", ephemeral=True)
        config = await self.bot.db.get_guild_config(interaction.guild.id)
        if not config or not all([config['raid_vc_template_id'], config['raid_channel_id']]):
            return await interaction.followup.send(embed=create_error_embed("Setup Incomplete", "The bot is not fully set up. Please ask an admin to re-invite the bot."))
        template_vc = interaction.guild.get_channel(config['raid_vc_template_id'])
        active_raids_channel = interaction.guild.get_channel(config['raid_channel_id'])
        if not template_vc or not active_raids_channel:
            return await interaction.followup.send(embed=create_error_embed("Setup Error", "Required channels are missing. Please re-invite the bot."))
        try:
            raid_date = datetime.now().strftime("%Y-%m-%d")
            new_vc = await template_vc.clone(name=f"Raid-{raid_date}")
            await new_vc.set_permissions(interaction.guild.default_role, view_channel=True)
            raid_message = await active_raids_channel.send(f"Raid started by {interaction.user.mention} on <t:{int(datetime.now().timestamp())}:F>")
            thread = await raid_message.create_thread(name=f"Raid Log - {raid_date}")
            await self.bot.db.execute(
                "INSERT INTO raids (guild_id, leader_id, vc_id, thread_id) VALUES (?, ?, ?, ?)",
                (interaction.guild.id, interaction.user.id, new_vc.id, thread.id)
            )
            control_embed = create_info_embed(
                f"Raid Control Panel for {interaction.user.display_name}",
                "Use the buttons below to manage your raid. This panel is only visible to you."
            )
            view = RaidControlView(self.bot)
            await thread.send(embed=control_embed, view=view)
            await interaction.followup.send(f"Raid created! Join {new_vc.mention} and manage it in {thread.mention}", ephemeral=True)
        except Exception as e:
            logging.error(f"Failed to create raid: {e}")
            await interaction.followup.send(embed=create_error_embed("Error", "Could not create the raid. Check my permissions."))

    @app_commands.command(name="raid_create", description="Creates a new raid channel and control thread.")
    @app_commands.checks.has_permissions(administrator=True)
    async def raid_create_cmd(self, interaction: discord.Interaction):
        await self.create_raid_from_interaction(interaction)

    @app_commands.command(name="raid_end", description="Ends and closes the current raid.")
    async def raid_end_cmd(self, interaction: discord.Interaction):
        if not await is_officer(interaction):
            return await interaction.response.send_message("You must be an officer or admin to end a raid.", ephemeral=True)
        await self.close_raid(interaction)

    @app_commands.command(name="award_dkp", description="Award DKP to a single member.")
    @app_commands.describe(member="Target member", points="Amount of DKP", reason="Reason for the award")
    async def award_dkp_cmd(self, interaction: discord.Interaction, member: discord.Member, points: int, reason: str | None = None):
        if not await is_officer(interaction):
            return await interaction.response.send_message("You must be an officer to use this command.", ephemeral=True)
        await self.process_dkp_adjustment(interaction, "Award", str(points), reason or "Manual Award", member)

    async def update_team_list(self, interaction: discord.Interaction):
        await interaction.response.defer()
        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        vc = interaction.guild.get_channel(raid['vc_id'])
        if not vc:
            return await interaction.followup.send("Raid voice channel not found.", ephemeral=True)
        members = vc.members
        if not members:
            return await interaction.followup.send("The voice channel is empty.")
        member_list = "\n".join([f"- {member.mention} ({member.display_name})" for member in members])
        embed = create_info_embed(
            "Current Raid Team",
            f"Last updated: <t:{int(datetime.now().timestamp())}:R>\n\n{member_list}"
        )
        await interaction.followup.send(embed=embed)

    async def process_dkp_adjustment(
        self,
        interaction: discord.Interaction,
        action: str,
        amount_str: str,
        reason: str,
        member: discord.Member | None = None,
    ):
        await interaction.response.defer()
        try:
            amount = int(amount_str)
            if amount <= 0:
                raise ValueError
        except ValueError:
            return await interaction.followup.send(
                embed=create_error_embed("Invalid Amount", "DKP amount must be a positive number."),
                ephemeral=True,
            )

        if action == "Deduct":
            amount = -amount

        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        vc = interaction.guild.get_channel(raid["vc_id"]) if raid else None

        if member is None:
            if not vc or not vc.members:
                return await interaction.followup.send(
                    "The raid voice channel is empty. No points awarded.",
                    ephemeral=True,
                )
            targets = [m for m in vc.members if not m.bot]
        else:
            targets = [] if member.bot else [member]

        for m in targets:
            await self.bot.db.modify_user_dkp(
                m.id,
                interaction.guild.id,
                amount,
                f"{action}: {reason} (Raid)",
            )

        action_word = "Awarded" if action == "Award" else "Deducted"
        if member:
            description = f"**{abs(amount)} DKP** {action_word.lower()} to {member.mention} for: *{reason}*."
        else:
            description = (
                f"**{abs(amount)} DKP** {action_word.lower()} to **{len(targets)}** players for: *{reason}*."
            )

        embed = create_success_embed(
            f"DKP {action_word}!",
            description,
        )
        await interaction.followup.send(embed=embed)
    async def close_raid(self, interaction: discord.Interaction):
        await interaction.response.defer()
        raid = await self.bot.db.get_raid_by_thread(interaction.channel.id)
        if not raid:
            return await interaction.followup.send("This raid is already closed or does not exist.", ephemeral=True)
        vc = interaction.guild.get_channel(raid['vc_id'])
        thread = interaction.channel
        # Deactivate raid in DB
        await self.bot.db.execute("UPDATE raids SET is_active = 0 WHERE id = ?", (raid['id'],))
        if vc:
            await vc.delete(reason="Raid closed.")
        await thread.send(f"Raid closed by {interaction.user.mention} at <t:{int(datetime.now().timestamp())}:F>. This thread is now locked.")
        await thread.edit(archived=True, locked=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(RaidCog(bot))
