"""Push-to-talk + live-audio control cog (``/voice`` commands).

Bridges a live Discord voice channel into the same intent -> dispatch path as
the typed ``/ai`` command. Voice is a PAID-tier feature; ``/voice start`` gates
on :func:`discord_bot.voice.tiering.load_entitlements` and meters voice-minutes,
stopping at the cap with one-shot 75% / 100% warnings.

Import-time contract
--------------------
This module is side-effect-free: the heavy live backends (``discord-ext-voice-recv``,
``deepgram-sdk``, ``faster-whisper``, ``anthropic``) are all lazy-imported by the
abstractions it builds, never at this module's import. In THIS environment the
voice-recv extension is not installed, so ``/voice start`` catches
:class:`VoiceReceiveUnavailable` / :class:`SttUnavailable` and replies with the
actionable remediation message instead of crashing — that is the expected path.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from ..utils import create_info_embed, create_success_embed, create_error_embed
from ..voice import (
    build_default_registry,
    ClaudeIntentParser,
    Dispatcher,
    DispatchContext,
    VoiceRecvAdapter,
    VoiceReceiveUnavailable,
)
from ..voice.session import VoiceSession, VoiceSessionConfig
from ..voice.stt import DeepgramStt, FasterWhisperStt, SttUnavailable
from ..voice.tiering import load_entitlements, usage_state, reset_if_new_period
from ..voice import personas as personas_mod
from ..voice.tts import ElevenLabsTts, TtsUnavailable, speak
from .voice_cog import VoiceCog


class _SpeakerContext:
    """Per-speaker stand-in passed as ``DispatchContext.interaction`` for voice.

    Voice has no per-utterance Discord ``Interaction``, but the dispatcher
    permission-checks ``ctx.interaction`` (``is_officer`` etc. read ``.guild``,
    ``.user`` and ``.client``). Reusing the ``/voice start`` invoker's interaction
    would let any speaker inherit the *starter's* permissions — a privilege
    escalation. This shim resolves the ACTUAL speaker so each command is
    authorized against the person who spoke it. An unresolved member (not cached)
    leaves ``user=None``, which the permission helpers treat as deny.
    """

    __slots__ = ("guild", "user", "client")

    def __init__(self, guild, user, client):
        self.guild = guild
        self.user = user
        self.client = client


def _select_stt():
    """Pick an STT engine from the environment (lazy backends; nothing imported
    here). Deepgram when a key is present, else local faster-whisper."""
    if os.environ.get("DEEPGRAM_API_KEY"):
        return DeepgramStt()
    return FasterWhisperStt()


def _select_tts():
    """Pick a TTS engine from the environment, or ``None`` to skip speak-back.

    ElevenLabs when a key is present (lazy SDK — nothing imported here); when no
    key is configured we return ``None`` and the cog degrades to text-only
    replies. This is the expected path in THIS environment.
    """
    if os.environ.get("ELEVENLABS_API_KEY"):
        return ElevenLabsTts()
    return None


class PttToggleView(discord.ui.View):
    """Author-bound control panel to toggle push-to-talk for a live session.

    Modeled on ``VoiceConfirmView`` — only the member who invoked ``/voice ptt``
    may flip the toggle, which mutates the live session's config in place.
    """

    def __init__(self, session: VoiceSession, *, invoker_id: int):
        super().__init__(timeout=300)
        self.session = session
        self.invoker_id = invoker_id
        self._sync_label()

    def _sync_label(self) -> None:
        on = self.session.config.push_to_talk
        self.toggle_btn.label = f"Push-to-talk: {'ON' if on else 'OFF'}"
        self.toggle_btn.style = (
            discord.ButtonStyle.success if on else discord.ButtonStyle.secondary
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.invoker_id:
            await interaction.response.send_message(
                embed=create_error_embed(
                    "Not your control panel",
                    "Only the person who opened this panel can toggle it.",
                ),
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Push-to-talk", style=discord.ButtonStyle.success)
    async def toggle_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.session.config.push_to_talk = not self.session.config.push_to_talk
        self._sync_label()
        state = "ON" if self.session.config.push_to_talk else "OFF"
        await interaction.response.edit_message(
            embed=create_info_embed(
                "Push-to-talk", f"Push-to-talk is now **{state}**."
            ),
            view=self,
        )


class VoiceControlCog(commands.Cog):
    """``/voice start|stop|ptt`` — live push-to-talk voice commands."""

    voice = app_commands.Group(
        name="voice", description="Live voice command controls (paid tier)."
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Per-guild live session state: guild_id -> {"session", "task"}.
        self._sessions: dict[int, dict] = {}

    # ------------------------------------------------------------------ #
    # /voice start
    # ------------------------------------------------------------------ #
    @voice.command(name="start", description="Start listening for voice commands.")
    async def start(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message(
                embed=create_error_embed(
                    "Server only", "This command can only be used in a server."
                ),
                ephemeral=True,
            )
            return

        guild_id = interaction.guild.id

        voice_state = getattr(interaction.user, "voice", None)
        if voice_state is None or voice_state.channel is None:
            await interaction.response.send_message(
                embed=create_error_embed(
                    "Join a voice channel first",
                    "You must be connected to a voice channel to start voice commands.",
                ),
                ephemeral=True,
            )
            return

        if guild_id in self._sessions:
            await interaction.response.send_message(
                embed=create_info_embed(
                    "Already listening",
                    "A voice session is already active in this server. Use `/voice stop` first.",
                ),
                ephemeral=True,
            )
            return

        # Reserve the slot BEFORE the awaits below to close the TOCTOU window:
        # two near-simultaneous /voice start calls would otherwise both pass the
        # guard above and start two receivers. The `finally` releases the
        # reservation unless we successfully started.
        self._sessions[guild_id] = {"session": None, "task": None}
        started = False
        try:
            await interaction.response.defer(ephemeral=True)

            # Roll the meter over at the start of a new billing period, then load
            # entitlements. Guard the DB access so a failure follows up the
            # deferred interaction instead of leaving the user on "thinking…".
            try:
                period = datetime.now(timezone.utc).strftime("%Y-%m")
                await reset_if_new_period(self.bot.db, guild_id, period)
                ent = await load_entitlements(self.bot.db, guild_id)
            except Exception:
                logging.exception("Voice start: entitlement lookup failed for guild %s", guild_id)
                await interaction.followup.send(
                    embed=create_error_embed(
                        "Couldn't start voice",
                        "A database error occurred while checking your plan. Please try again.",
                    ),
                    ephemeral=True,
                )
                return

            # --- PAID gate + metering cap ------------------------------ #
            if not ent.voice_allowed:
                await interaction.followup.send(
                    embed=create_info_embed(
                        "Voice is a paid feature",
                        "Live voice commands require the **paid** tier. Upgrade to "
                        "unlock push-to-talk voice control.",
                    ),
                    ephemeral=True,
                )
                return
            if ent.level == "capped":
                await interaction.followup.send(
                    embed=create_info_embed(
                        "Voice minutes used up",
                        f"This server has used all {int(ent.minutes_limit)} voice "
                        "minutes for the period. Usage resets next cycle.",
                    ),
                    ephemeral=True,
                )
                return

            voice_channel = voice_state.channel
            reply_channel = interaction.channel

            # --- Build the live session behind the seam ---------------- #
            registry = build_default_registry()
            dispatcher = Dispatcher(registry)
            session = VoiceSession(
                receiver=VoiceRecvAdapter(),
                stt=_select_stt(),
                intent_parser=ClaudeIntentParser(),
                registry=registry,
                dispatcher=dispatcher,
                make_ctx=self._make_ctx_factory(interaction, guild_id),
                on_result=self._on_result_factory(reply_channel, guild_id),
                on_notice=self._on_notice_factory(reply_channel),
                meter=self._meter_factory(guild_id, reply_channel),
                config=VoiceSessionConfig(push_to_talk=True),
            )

            # Start capture eagerly so the missing-extension case surfaces NOW
            # with an actionable message, not silently in the background task.
            try:
                await session.start_capture(voice_channel)
            except (VoiceReceiveUnavailable, SttUnavailable) as exc:
                await interaction.followup.send(
                    embed=create_error_embed("Voice receive unavailable", str(exc)),
                    ephemeral=True,
                )
                return
            except Exception:  # pragma: no cover - live path
                logging.exception("Unexpected error starting voice receive")
                await interaction.followup.send(
                    embed=create_error_embed(
                        "Couldn't start voice", "An unexpected error occurred starting voice capture."
                    ),
                    ephemeral=True,
                )
                return

            # receiver already started; the background task consumes the stream.
            task = asyncio.create_task(self._run_session(guild_id, session))
            self._sessions[guild_id] = {"session": session, "task": task}
            started = True

            await interaction.followup.send(
                embed=create_success_embed(
                    "Listening",
                    f"Voice commands are active in **{voice_channel.name}**. "
                    "Speak a command, or use `/voice ptt` to toggle push-to-talk.",
                ),
                ephemeral=True,
            )
        finally:
            # Release the reservation if we didn't actually start (early return,
            # gate failure, or exception). The background task owns cleanup once
            # started.
            if not started:
                self._sessions.pop(guild_id, None)

    async def _run_session(self, guild_id, session):  # pragma: no cover - live path
        """Consume the already-started receiver until it ends, then clean up."""
        try:
            await session.consume()
        except Exception:
            logging.exception("Voice session for guild %s crashed", guild_id)
        finally:
            self._sessions.pop(guild_id, None)

    # ------------------------------------------------------------------ #
    # /voice stop
    # ------------------------------------------------------------------ #
    @voice.command(name="stop", description="Stop listening for voice commands.")
    async def stop(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message(
                embed=create_error_embed(
                    "Server only", "This command can only be used in a server."
                ),
                ephemeral=True,
            )
            return

        entry = self._sessions.pop(interaction.guild.id, None)
        if entry is None:
            await interaction.response.send_message(
                embed=create_info_embed(
                    "Not listening", "There's no active voice session in this server."
                ),
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        try:
            await entry["session"].stop()
        except Exception:  # pragma: no cover - live path
            logging.exception("Error stopping voice session")
        task = entry.get("task")
        if task is not None:
            task.cancel()

        await interaction.followup.send(
            embed=create_success_embed("Stopped", "Voice commands are now off."),
            ephemeral=True,
        )

    # ------------------------------------------------------------------ #
    # /voice ptt
    # ------------------------------------------------------------------ #
    @voice.command(name="ptt", description="Toggle push-to-talk for the voice session.")
    async def ptt(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message(
                embed=create_error_embed(
                    "Server only", "This command can only be used in a server."
                ),
                ephemeral=True,
            )
            return

        entry = self._sessions.get(interaction.guild.id)
        if entry is None:
            await interaction.response.send_message(
                embed=create_info_embed(
                    "Not listening",
                    "Start a voice session with `/voice start` before toggling push-to-talk.",
                ),
                ephemeral=True,
            )
            return

        session = entry["session"]
        view = PttToggleView(session, invoker_id=interaction.user.id)
        state = "ON" if session.config.push_to_talk else "OFF"
        await interaction.response.send_message(
            embed=create_info_embed(
                "Push-to-talk", f"Push-to-talk is currently **{state}**. Tap to toggle."
            ),
            view=view,
            ephemeral=True,
        )

    # ------------------------------------------------------------------ #
    # /voice persona
    # ------------------------------------------------------------------ #
    @voice.command(
        name="persona",
        description="Choose the TTS voice persona for spoken replies (paid tier).",
    )
    @app_commands.describe(name="The persona to speak command results with.")
    @app_commands.choices(
        name=[
            app_commands.Choice(name=p.display_name, value=p.key)
            for p in personas_mod.list_personas()
        ]
    )
    async def persona(self, interaction: discord.Interaction, name: str):
        if interaction.guild is None:
            await interaction.response.send_message(
                embed=create_error_embed(
                    "Server only", "This command can only be used in a server."
                ),
                ephemeral=True,
            )
            return

        guild_id = interaction.guild.id

        # Defer up front: the DB reads/writes below could exceed the 3-second
        # response window, and deferring lets a DB error follow up cleanly
        # instead of leaving the interaction hanging.
        await interaction.response.defer(ephemeral=True)

        try:
            # PAID gate — personas are a paid-tier speak-back feature.
            ent = await load_entitlements(self.bot.db, guild_id)
            if not ent.voice_allowed:
                await interaction.followup.send(
                    embed=create_info_embed(
                        "Personas are a paid feature",
                        "Spoken replies with selectable personas require the "
                        "**paid** tier.",
                    ),
                    ephemeral=True,
                )
                return

            valid = {p.key for p in personas_mod.list_personas()}
            if name not in valid:
                options = ", ".join(f"`{p.key}`" for p in personas_mod.list_personas())
                await interaction.followup.send(
                    embed=create_error_embed(
                        "Unknown persona",
                        f"`{name}` is not a valid persona. Choose one of: {options}.",
                    ),
                    ephemeral=True,
                )
                return

            await self.bot.db.set_voice_persona(guild_id, name)
        except Exception:
            logging.exception("Voice persona update failed for guild %s", guild_id)
            await interaction.followup.send(
                embed=create_error_embed(
                    "Couldn't update persona",
                    "A database error occurred. Please try again.",
                ),
                ephemeral=True,
            )
            return

        persona = personas_mod.get_persona(name)
        await interaction.followup.send(
            embed=create_success_embed(
                "Persona updated",
                f"Spoken replies will now use **{persona.display_name}** "
                f"({persona.style}).",
            ),
            ephemeral=True,
        )

    # ------------------------------------------------------------------ #
    # Session callback factories
    # ------------------------------------------------------------------ #
    def _make_ctx_factory(self, interaction, guild_id):
        guild = interaction.guild
        bot = self.bot

        def make_ctx(user_id: int) -> DispatchContext:
            # Resolve the ACTUAL speaker so permission checks key off them, not
            # the /voice start invoker (see _SpeakerContext). get_member returns
            # None when uncached, which the permission helpers treat as deny.
            member = guild.get_member(user_id) if guild is not None else None
            return DispatchContext(
                bot=bot,
                interaction=_SpeakerContext(guild=guild, user=member, client=bot),
                guild_id=guild_id,
                actor_id=user_id,
            )

        return make_ctx

    def _on_result_factory(self, channel, guild_id):
        async def on_result(user_id, intent, result):  # pragma: no cover - live path
            if result.status == "needs_confirmation":
                embed = create_info_embed(
                    "Confirmation needed",
                    f"<@{user_id}>: {result.confirm_summary or result.message} "
                    "Re-issue this as `/ai` to confirm — destructive voice "
                    "commands are not auto-confirmed.",
                )
            else:
                embed = VoiceCog._result_embed(result)
            try:
                await channel.send(embed=embed)
            except Exception:
                logging.exception("Failed to deliver voice command result")

            # Best-effort TTS speak-back. The text embed above is already the
            # authoritative reply; speaking is a paid-tier bonus that degrades
            # silently if there's no engine/voice client or it fails.
            await self._maybe_speak(guild_id, result)

        return on_result

    async def _maybe_speak(self, guild_id, result):  # pragma: no cover - live path
        """Speak ``result`` into the live voice channel if possible (best-effort).

        Skips silently when: no TTS engine is configured (no ELEVENLABS_API_KEY),
        the guild is not paid, there's no active session/voice client, or the
        engine is unavailable. The text embed has already been delivered, so any
        failure here is non-fatal.
        """
        tts = _select_tts()
        if tts is None:
            return

        ent = await load_entitlements(self.bot.db, guild_id)
        if not ent.voice_allowed:
            return

        entry = self._sessions.get(guild_id)
        if entry is None:
            return
        voice_client = getattr(entry["session"].receiver, "voice_client", None)
        if voice_client is None:
            return

        cfg = await self.bot.db.get_guild_config(guild_id)
        keys = cfg.keys() if cfg is not None else []
        persona_key = (
            cfg["voice_persona"]
            if cfg is not None and "voice_persona" in keys
            else personas_mod.DEFAULT_PERSONA_KEY
        )
        persona = personas_mod.get_persona(persona_key)

        summary = (result.message or "").strip()
        if not summary:
            return

        try:
            await speak(voice_client, tts, summary, persona)
        except TtsUnavailable:
            # SDK/key missing at synth time — degrade to the text embed only.
            logging.info("TTS unavailable; spoke-back skipped for guild %s", guild_id)
        except Exception:
            logging.exception("TTS speak-back failed for guild %s", guild_id)

    def _on_notice_factory(self, channel):
        async def on_notice(message: str):  # pragma: no cover - live path
            try:
                await channel.send(embed=create_info_embed("Voice", message))
            except Exception:
                logging.exception("Failed to deliver voice notice")

        return on_notice

    def _meter_factory(self, guild_id, channel):
        async def meter(minutes: float):  # pragma: no cover - live path
            await self.bot.db.add_voice_minutes(guild_id, minutes)
            ent = await load_entitlements(self.bot.db, guild_id)
            state = usage_state(ent.minutes_used, ent.minutes_limit)
            level = state["level"]

            cfg = await self.bot.db.get_guild_config(guild_id)
            keys = cfg.keys() if cfg is not None else []
            warn75 = bool(cfg["voice_warn_75_sent"]) if "voice_warn_75_sent" in keys else False
            warn100 = bool(cfg["voice_warn_100_sent"]) if "voice_warn_100_sent" in keys else False

            # One-shot 75% warning (mirrors the existing warning_sent pattern).
            # Gated to the "warn" band only: a jump straight to "capped" gets the
            # 100% message below instead, so the two never fire on the same tick.
            # Set the flag only AFTER a successful send so a delivery failure is
            # retried next tick rather than silently suppressing the warning.
            if level == "warn" and not warn75:
                try:
                    await channel.send(
                        embed=create_info_embed(
                            "Voice minutes 75%",
                            f"This server has used {int(ent.minutes_used)} of "
                            f"{int(ent.minutes_limit)} voice minutes.",
                        )
                    )
                    await self.bot.db.execute(
                        "UPDATE guilds SET voice_warn_75_sent = 1 WHERE guild_id = ?",
                        (guild_id,),
                    )
                except Exception:
                    logging.exception("Failed to send 75% voice warning")

            # One-shot 100% warning.
            if level == "capped" and not warn100:
                try:
                    await channel.send(
                        embed=create_error_embed(
                            "Voice minutes used up",
                            "This server has reached its voice-minute cap; the "
                            "session will stop.",
                        )
                    )
                    await self.bot.db.execute(
                        "UPDATE guilds SET voice_warn_100_sent = 1 WHERE guild_id = ?",
                        (guild_id,),
                    )
                except Exception:
                    logging.exception("Failed to send 100% voice warning")

            return level

        return meter


async def setup(bot: commands.Bot):
    await bot.add_cog(VoiceControlCog(bot))
