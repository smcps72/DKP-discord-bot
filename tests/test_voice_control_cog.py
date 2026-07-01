"""Regression tests for the /voice control cog's per-speaker context.

The security-critical property: a voice command must be permission-checked
against the member who SPOKE it, not the member who ran /voice start. The
permission helpers read ctx.interaction.user, so the per-speaker DispatchContext
must carry the resolved speaker there.
"""

from unittest.mock import MagicMock

from discord_bot.cogs.voice_control_cog import VoiceControlCog, _SpeakerContext


def test_make_ctx_resolves_actual_speaker_not_invoker():
    bot = MagicMock()
    cog = VoiceControlCog(bot)

    invoker = MagicMock()
    invoker.id = 1
    speaker_member = MagicMock()
    speaker_member.id = 999

    guild = MagicMock()
    guild.get_member.return_value = speaker_member

    interaction = MagicMock()
    interaction.guild = guild
    interaction.user = invoker

    make_ctx = cog._make_ctx_factory(interaction, guild.id)
    ctx = make_ctx(999)

    # Permission checks read ctx.interaction.user — it MUST be the speaker, never
    # the /voice start invoker (otherwise the speaker inherits the invoker's perms).
    assert isinstance(ctx.interaction, _SpeakerContext)
    assert ctx.interaction.user is speaker_member
    assert ctx.interaction.user is not invoker
    assert ctx.interaction.guild is guild
    assert ctx.interaction.client is bot
    assert ctx.actor_id == 999
    guild.get_member.assert_called_once_with(999)


def test_make_ctx_uncached_member_is_deny_safe():
    bot = MagicMock()
    cog = VoiceControlCog(bot)

    guild = MagicMock()
    guild.get_member.return_value = None  # member not in cache

    interaction = MagicMock()
    interaction.guild = guild

    make_ctx = cog._make_ctx_factory(interaction, 5)
    ctx = make_ctx(42)

    # No resolvable member -> user is None, which the permission helpers treat as
    # a non-member (deny). Fail-safe, not fail-open.
    assert ctx.interaction.user is None
    assert ctx.actor_id == 42
