"""Voice / natural-language command cog.

Exposes ``/ai <request>`` — the user describes what they want in plain language,
an LLM maps it to one registered command, the dispatcher validates / permission-
checks / confirms, and a handler reusing ``bot.db`` runs it. All responses are
ephemeral.
"""

import logging
import os

import discord
from discord import app_commands
from discord.ext import commands

from ..utils import create_info_embed, create_success_embed, create_error_embed
from ..voice import (
    build_default_registry,
    ClaudeIntentParser,
    Dispatcher,
    DispatchContext,
)


class VoiceConfirmView(discord.ui.View):
    """Confirm/Cancel view shown for destructive AI commands.

    Modeled on ``GuildBankFuzzyMatchView`` — disables its buttons on click and
    edits the original ephemeral message with the result.
    """

    def __init__(self, cog, *, dispatcher, intent, ctx, invoker_id):
        super().__init__(timeout=120)
        self.cog = cog
        self.dispatcher = dispatcher
        self.intent = intent
        self.ctx = ctx
        self.invoker_id = invoker_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Only the member who issued the /ai command may confirm/cancel it.
        if interaction.user.id != self.invoker_id:
            await interaction.response.send_message(
                embed=create_error_embed(
                    "Not your confirmation",
                    "Only the person who issued this command can confirm it.",
                ),
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
    async def confirm_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        result = await self.dispatcher.dispatch(self.intent, self.ctx, confirmed=True)
        embed = self.cog._result_embed(result)
        await interaction.edit_original_response(embed=embed, view=None)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.edit_original_response(
            embed=create_info_embed("Cancelled", "No changes were made."),
            view=None,
        )


class VoiceCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @staticmethod
    def _result_embed(result) -> discord.Embed:
        if result.status == "ok":
            return create_success_embed("Done", result.message)
        if result.status in ("denied", "invalid_args", "unknown_command", "error"):
            return create_error_embed("Couldn't run that", result.message)
        return create_info_embed("AI command", result.message)

    @app_commands.command(
        name="ai",
        description="Tell the bot what to do in plain language.",
    )
    @app_commands.describe(request="What you want the bot to do, in plain language.")
    async def ai(self, interaction: discord.Interaction, request: str):
        if interaction.guild is None:
            await interaction.response.send_message(
                embed=create_error_embed(
                    "Server only", "This command can only be used in a server."
                ),
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        if not os.environ.get("ANTHROPIC_API_KEY"):
            await interaction.followup.send(
                embed=create_info_embed(
                    "AI not configured",
                    "AI command parsing isn't configured (set ANTHROPIC_API_KEY).",
                ),
                ephemeral=True,
            )
            return

        registry = build_default_registry()
        dispatcher = Dispatcher(registry)
        parser = ClaudeIntentParser()

        ctx = DispatchContext(
            bot=self.bot,
            interaction=interaction,
            guild_id=interaction.guild.id,
            actor_id=interaction.user.id,
        )

        try:
            intent = await parser.parse(request, registry)
        except Exception:
            logging.exception("AI intent parsing failed")
            await interaction.followup.send(
                embed=create_error_embed(
                    "Parsing failed", "I couldn't process that request right now."
                ),
                ephemeral=True,
            )
            return

        result = await dispatcher.dispatch(intent, ctx)

        if result.status == "needs_confirmation":
            view = VoiceConfirmView(
                self,
                dispatcher=dispatcher,
                intent=intent,
                ctx=ctx,
                invoker_id=interaction.user.id,
            )
            await interaction.followup.send(
                embed=create_info_embed(
                    "Confirm action", result.confirm_summary or result.message
                ),
                view=view,
                ephemeral=True,
            )
            return

        await interaction.followup.send(embed=self._result_embed(result), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(VoiceCog(bot))
