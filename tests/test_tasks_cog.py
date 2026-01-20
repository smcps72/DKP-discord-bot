import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta
import os # <--- Added import

import discord
from discord.ext import tasks # Import tasks

# Adjust the import path if your project structure is different
from discord_bot.cogs.tasks_cog import TasksCog


# This is a common pattern for testing tasks.loop
async def immediate_loop_side_effect(loop_instance, *args, **kwargs):
    """Side effect for Loop.start() that calls the loop's coroutine immediately."""
    # loop_instance is 'self' for the Loop object, which has the .coro attribute
    # In discord.py 2.x, the coroutine is often stored in _coro
    actual_coro = None
    if hasattr(loop_instance, 'coro') and asyncio.iscoroutinefunction(loop_instance.coro):
        actual_coro = loop_instance.coro
    elif hasattr(loop_instance, '_coro') and asyncio.iscoroutinefunction(loop_instance._coro):
        actual_coro = loop_instance._coro

    if actual_coro:
        # If the loop has before_loop and after_loop, a more complete mock would call them.
        # For simplicity, we directly invoke the main task coroutine.
        # Note: The original Loop.start() also handles _lock, _task, _current_loop etc.
        # This simplified version is for testing the *logic* of the task method itself.
        if loop_instance._before_loop is not None: # Check if before_loop is defined
            try:
                await loop_instance._before_loop()
            except Exception as e:
                print(f"Error in before_loop for {actual_coro.__name__}: {e}") # Or log, or re-raise
                return # Potentially stop if before_loop fails critically

        await actual_coro(*args, **kwargs) # Call the original async function

        if loop_instance._after_loop is not None: # Check if after_loop is defined
            try:
                await loop_instance._after_loop()
            except Exception as e:
                print(f"Error in after_loop for {actual_coro.__name__}: {e}") 
    else:
        print(f"Warning: Loop instance {loop_instance} (name: {loop_instance.name if hasattr(loop_instance, 'name') else 'N/A'}) did not have a callable 'coro' or '_coro'. Attributes: {dir(loop_instance)}")


class TestTasksCog(unittest.IsolatedAsyncioTestCase):

    @patch('discord.ext.tasks.Loop.start', new_callable=MagicMock)
    def setUp(self, mock_loop_start_method): 
        self.bot = AsyncMock() 
        self.bot.guilds = []
        self.bot.license_check_enabled = True 

        self.bot.http_session = MagicMock(name="aiohttp_ClientSession_mock")
        self.bot.http_session.post = MagicMock(name="session.post_method_mock")
        self.bot.http_session.close = AsyncMock(name="session.close_method_mock")

        self.bot.get_channel = MagicMock(name="bot.get_channel_mock") 

        self.bot.db = AsyncMock() 
        self.bot.license_key = "test_license_key"
        self.bot.license_server_url = "http://testserver.com"

        self.cog = TasksCog(self.bot)
        self.mock_loop_start_method = mock_loop_start_method 

    async def test_dummy(self):
        self.assertTrue(True)
        if self.bot.license_check_enabled:
            self.assertEqual(self.mock_loop_start_method.call_count, 5)
        else:
            self.assertEqual(self.mock_loop_start_method.call_count, 4)


    def _setup_mock_http_response(self, status_code, json_payload=None, exception_to_raise=None):
        mock_aiohttp_response = AsyncMock() 
        mock_aiohttp_response.status = status_code
        if json_payload is not None:
            mock_aiohttp_response.json = AsyncMock(return_value=json_payload)

        mock_async_context_manager = AsyncMock() 
        if exception_to_raise:
            mock_async_context_manager.__aenter__.side_effect = exception_to_raise
        else:
            mock_async_context_manager.__aenter__.return_value = mock_aiohttp_response
        mock_async_context_manager.__aexit__ = AsyncMock(return_value=None) 

        self.bot.http_session.post.return_value = mock_async_context_manager


    async def test_license_check_valid_license(self):
        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.id = 12345
        self.bot.guilds = [mock_guild]
        self.bot.db.get_guild_config.return_value = {'dkp_channel_id': 67890, 'warning_sent': 0, 'license_status': 'unknown'}

        self._setup_mock_http_response(status_code=200, json_payload={"status": "active"})

        await self.cog.license_check()

        self.bot.http_session.post.assert_called_once_with(
            f"{self.bot.license_server_url}/check_license",
            json={"license_key": self.bot.license_key}
        )
        self.bot.db.execute.assert_any_call("UPDATE guilds SET license_status = ? WHERE guild_id = ?", ("active", mock_guild.id))
        self.bot.db.get_guild_config.return_value['warning_sent'] = 1 
        await self.cog.license_check() 
        self.bot.db.execute.assert_any_call("UPDATE guilds SET warning_sent = 0 WHERE guild_id = ?", (mock_guild.id,))


    async def test_license_check_lapsed_license_sends_warning(self):
        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.id = 12345
        self.bot.guilds = [mock_guild]

        mock_dkp_channel = AsyncMock(spec=discord.TextChannel)
        self.bot.get_channel.return_value = mock_dkp_channel

        self.bot.db.get_guild_config.return_value = {'dkp_channel_id': 67890, 'warning_sent': 0, 'license_status': 'active'}

        self._setup_mock_http_response(status_code=200, json_payload={"status": "lapsed"})

        await self.cog.license_check()

        self.bot.http_session.post.assert_called_once_with(
            f"{self.bot.license_server_url}/check_license",
            json={"license_key": self.bot.license_key}
        )
        self.bot.db.execute.assert_any_call("UPDATE guilds SET license_status = ? WHERE guild_id = ?", ("lapsed", mock_guild.id))
        mock_dkp_channel.send.assert_called_once()
        self.bot.db.execute.assert_any_call("UPDATE guilds SET warning_sent = 1 WHERE guild_id = ?", (mock_guild.id,))

    async def test_license_check_lapsed_license_warning_already_sent(self):
        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.id = 12345
        self.bot.guilds = [mock_guild]

        mock_dkp_channel = AsyncMock(spec=discord.TextChannel)
        self.bot.get_channel.return_value = mock_dkp_channel

        self.bot.db.get_guild_config.return_value = {'dkp_channel_id': 67890, 'warning_sent': 1, 'license_status': 'lapsed'}

        self._setup_mock_http_response(status_code=200, json_payload={"status": "lapsed"})

        await self.cog.license_check()

        mock_dkp_channel.send.assert_not_called() 
        self.bot.db.execute.assert_any_call("UPDATE guilds SET license_status = ? WHERE guild_id = ?", ("lapsed", mock_guild.id))
        update_warning_sent_calls = [
            call for call in self.bot.db.execute.call_args_list
            if call[0][0] == "UPDATE guilds SET warning_sent = ? WHERE guild_id = ?" and call[0][1] == 1
        ]
        self.assertEqual(len(update_warning_sent_calls), 0)


    async def test_license_check_http_error(self):
        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.id = 12345
        self.bot.guilds = [mock_guild]
        self.bot.db.get_guild_config.return_value = {'dkp_channel_id': 67890, 'warning_sent': 0}

        self._setup_mock_http_response(status_code=500) 

        with self.assertLogs(None, level='ERROR') as log: 
            await self.cog.license_check()

        self.assertTrue(any("Failed to check license. Status: 500" in message for message in log.output),
                        f"Expected log message not found. Logs: {log.output}")

        self.bot.db.execute.assert_not_called() 


    async def test_license_check_connection_error(self):
        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.id = 12345
        self.bot.guilds = [mock_guild]
        self.bot.db.get_guild_config.return_value = {'dkp_channel_id': 67890, 'warning_sent': 0}

        simulated_error = ConnectionError("Simulated connection/network error")
        self._setup_mock_http_response(status_code=None, exception_to_raise=simulated_error)

        with self.assertLogs(None, level='ERROR') as log: 
            await self.cog.license_check()

        self.assertTrue(any(f"Error connecting to licensing server at {self.bot.license_server_url}" in message for message in log.output),
                        f"Expected connection error log message not found. Logs: {log.output}")
        self.bot.db.execute.assert_not_called()


    async def test_license_check_no_license_key(self):
        self.bot.license_key = None 
        with self.assertLogs(level='WARNING') as log:
            await self.cog.license_check()
            self.assertTrue(any("No license key found" in message for message in log.output))

        self.bot.http_session.post.assert_not_called()
        self.bot.db.execute.assert_not_called()

    @patch('discord.ext.tasks.Loop.start', new_callable=MagicMock)
    async def test_license_check_disabled_in_cog_init(self, mock_loop_start_override_method):
        self.bot_specific = AsyncMock() 
        self.bot_specific.guilds = []
        self.bot_specific.license_check_enabled = False 
        self.bot_specific.http_session = AsyncMock()
        self.bot_specific.db = AsyncMock()
        self.bot_specific.license_key = "test_license_key"
        self.bot_specific.license_server_url = "http://testserver.com"

        cog_disabled = TasksCog(self.bot_specific)

        self.assertEqual(mock_loop_start_override_method.call_count, 4)


    async def test_hourly_dkp_award_only_active_raid_members(self):
        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.id = 12345

        member1 = MagicMock(spec=discord.Member)
        member1.id = 111
        member1.bot = False
        member2 = MagicMock(spec=discord.Member)
        member2.id = 222
        member2.bot = False
        bot_member = MagicMock(spec=discord.Member)
        bot_member.id = 333
        bot_member.bot = True

        def get_member_side_effect(user_id):
            if int(user_id) == 111:
                return member1
            if int(user_id) == 222:
                return member2
            if int(user_id) == 333:
                return bot_member
            return None

        mock_guild.get_member.side_effect = get_member_side_effect

        self.bot.guilds = [mock_guild]
        self.bot.db.fetchall = AsyncMock(return_value=[
            {"user_id": 111},
            {"user_id": 222},
            {"user_id": 222},
            {"user_id": 333},
        ])
        self.bot.db.modify_user_dkp = AsyncMock()

        await self.cog.hourly_dkp_award()

        self.bot.db.modify_user_dkp.assert_any_call(111, 12345, 5, "Hourly award")
        self.bot.db.modify_user_dkp.assert_any_call(222, 12345, 5, "Hourly award")
        calls = [c for c in self.bot.db.modify_user_dkp.call_args_list if c[0][0] == 333]
        self.assertEqual(len(calls), 0)

    async def test_cleanup_channels_empty_raid_vc_deleted(self):
        mock_vc = AsyncMock(spec=discord.VoiceChannel)
        mock_vc.id = 1001
        mock_vc.name = "Raid VC Alpha"
        mock_vc.members = [] 
        mock_vc.members = [] # Empty

        self.bot.db.fetchall.return_value = [{'vc_id': mock_vc.id}]
        self.bot.get_channel.return_value = mock_vc

        await self.cog.cleanup_channels()

        self.bot.db.fetchall.assert_called_once_with("SELECT id, vc_id FROM raids WHERE is_active = 1")
        self.bot.get_channel.assert_called_once_with(mock_vc.id)
        mock_vc.delete.assert_not_called()
        # Raids remain active; we simply clear vc_id when the VC is empty.
        self.bot.db.execute.assert_called_once_with(
            "UPDATE raids SET vc_id = NULL WHERE vc_id = ? AND is_active = 1",
            (mock_vc.id,),
        )

    async def test_cleanup_channels_vc_with_members_not_deleted(self):
        # Mock an active raid with a VC that has members
        mock_vc_with_users = AsyncMock(spec=discord.VoiceChannel)
        mock_vc_with_users.id = 1002
        mock_vc_with_users.name = "Raid VC Bravo (Active)"
        mock_vc_with_users.members = [MagicMock(spec=discord.Member)] # Has members

        self.bot.db.fetchall.return_value = [{'vc_id': mock_vc_with_users.id}]
        self.bot.get_channel.return_value = mock_vc_with_users

        # Reset execute mock for this specific test if needed, or ensure calls are distinct
        self.bot.db.execute.reset_mock()

        await self.cog.cleanup_channels()

        self.bot.get_channel.assert_called_once_with(mock_vc_with_users.id)
        mock_vc_with_users.delete.assert_not_called()
        self.bot.db.execute.assert_not_called() # DB entry should not be updated

    async def test_cleanup_channels_vc_not_found(self):
        # Mock a raid where the VC ID does not resolve to a channel
        self.bot.db.fetchall.return_value = [{'vc_id': 9999}] # Non-existent VC ID
        self.bot.get_channel.return_value = None # Simulate channel not found

        self.bot.db.execute.reset_mock()

        await self.cog.cleanup_channels()

        self.bot.get_channel.assert_called_once_with(9999)
        # When a VC can't be resolved, clear vc_id so the raid isn't tied to a stale channel.
        self.bot.db.execute.assert_called_once_with(
            "UPDATE raids SET vc_id = NULL WHERE vc_id = ? AND is_active = 1",
            (9999,),
        )

    async def test_cleanup_channels_not_a_voice_channel(self):
        # Mock a raid where the channel ID resolves to a TextChannel
        mock_text_channel = AsyncMock(spec=discord.TextChannel) # Not a VoiceChannel
        mock_text_channel.id = 1003

        self.bot.db.fetchall.return_value = [{'vc_id': mock_text_channel.id}]
        self.bot.get_channel.return_value = mock_text_channel

        self.bot.db.execute.reset_mock()

        await self.cog.cleanup_channels()

        self.bot.get_channel.assert_called_once_with(mock_text_channel.id)
        # mock_text_channel does not have a .delete method in the same way,
        # and the cog specifically checks `isinstance(channel, discord.VoiceChannel)`
        # so no delete should be attempted on it by channel.delete()
        # and no db update should occur.
        self.bot.db.execute.assert_not_called()


    async def test_cleanup_channels_no_active_raids(self):
        self.bot.db.fetchall.return_value = [] # No active raids

        self.bot.get_channel.reset_mock()
        self.bot.db.execute.reset_mock()

        await self.cog.cleanup_channels()

        self.bot.db.fetchall.assert_called_once_with("SELECT id, vc_id FROM raids WHERE is_active = 1")
        self.bot.get_channel.assert_not_called()
        self.bot.db.execute.assert_not_called()


    async def test_enforce_raid_voice_absences_skips_when_no_voice_channels(self):
        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.id = 12345
        mock_guild.get_channel.return_value = None
        self.bot.get_guild = MagicMock(return_value=mock_guild)

        self.bot.db.fetchall = AsyncMock(return_value=[
            {"id": 1, "guild_id": 12345, "leader_id": 111, "thread_id": 222, "vc_id": None},
        ])
        self.bot.db.get_raid_voice_channels = AsyncMock(return_value=[])
        self.bot.db.get_raid_members = AsyncMock(return_value=[{"user_id": 111}])
        self.bot.db.remove_raid_member = AsyncMock()

        await self.cog.enforce_raid_voice_absences()

        self.bot.db.remove_raid_member.assert_not_called()
        self.bot.db.execute.assert_any_call(
            "DELETE FROM raid_voice_absences WHERE raid_id = ?",
            (1,),
        )


    async def test_enforce_raid_voice_absences_removes_after_15_minutes(self):
        class FakeVoiceChannel:
            def __init__(self, members=None):
                self.members = members or []

        member_id = 555
        raid_id = 1
        guild_id = 12345
        vc_id = 999

        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.id = guild_id
        mock_guild.get_thread = MagicMock(return_value=None)
        mock_guild.get_member = MagicMock(return_value=None)

        fake_vc = FakeVoiceChannel(members=[])
        mock_guild.get_channel = MagicMock(return_value=fake_vc)
        self.bot.get_guild = MagicMock(return_value=mock_guild)

        from discord_bot.cogs import tasks_cog as tasks_cog_module
        with patch.object(tasks_cog_module.discord, "VoiceChannel", FakeVoiceChannel):
            self.bot.db.fetchall = AsyncMock(return_value=[
                {"id": raid_id, "guild_id": guild_id, "leader_id": 111, "thread_id": 222, "vc_id": vc_id},
            ])
            self.bot.db.get_raid_voice_channels = AsyncMock(return_value=[])
            self.bot.db.get_raid_members = AsyncMock(return_value=[{"user_id": member_id}])
            self.bot.db.is_raid_member_excluded = AsyncMock(return_value=False)

            absent_since = (datetime.utcnow() - timedelta(minutes=16)).isoformat()
            self.bot.db.fetchone = AsyncMock(return_value={"absent_since": absent_since})
            self.bot.db.remove_raid_member = AsyncMock(return_value=True)
            self.bot.db.add_raid_member_exclusion = AsyncMock()
            self.bot.db.delete_raid_join_request = AsyncMock()

            await self.cog.enforce_raid_voice_absences()

            self.bot.db.remove_raid_member.assert_called_once_with(raid_id, member_id)
            self.bot.db.add_raid_member_exclusion.assert_called_once_with(raid_id, member_id)
            self.bot.db.delete_raid_join_request.assert_called_once_with(raid_id, member_id)
            self.bot.db.execute.assert_any_call(
                "DELETE FROM raid_member_groups WHERE raid_id = ? AND user_id = ?",
                (raid_id, member_id),
            )
            self.bot.db.execute.assert_any_call(
                "DELETE FROM raid_voice_absences WHERE raid_id = ? AND user_id = ?",
                (raid_id, member_id),
            )


if __name__ == '__main__':
    unittest.main()
