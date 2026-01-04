import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
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
                print(f"Error in after_loop for {actual_coro.__name__}: {e}") # Or log
    else:
        print(f"Warning: Loop instance {loop_instance} (name: {loop_instance.name if hasattr(loop_instance, 'name') else 'N/A'}) did not have a callable 'coro' or '_coro'. Attributes: {dir(loop_instance)}")


class TestTasksCog(unittest.IsolatedAsyncioTestCase):

    @patch('discord.ext.tasks.Loop.start', new_callable=AsyncMock, side_effect=immediate_loop_side_effect)
    def setUp(self, mock_loop_start_method): # mock_loop_start_method is now an AsyncMock
        self.bot = AsyncMock() # Use AsyncMock for bot as it has async methods
        self.bot.guilds = []
        self.bot.license_check_enabled = True # Assume it's enabled for testing tasks

        # Mocking aiohttp.ClientSession behavior:
        # self.bot.http_session should represent the session object.
        # self.bot.http_session.post is a method that returns an async context manager.
        self.bot.http_session = MagicMock(name="aiohttp_ClientSession_mock")
        self.bot.http_session.post = MagicMock(name="session.post_method_mock")
        # self.bot.http_session.close is an async method, if used by the cog's shutdown.
        self.bot.http_session.close = AsyncMock(name="session.close_method_mock")

        self.bot.get_channel = MagicMock(name="bot.get_channel_mock") # discord.Client.get_channel is sync

        self.bot.db = AsyncMock() # For database interactions
        self.bot.license_key = "test_license_key"
        self.bot.license_server_url = "http://testserver.com"

        # Initialize the cog *after* patching tasks.Loop.start
        # so that the @tasks.loop decorators in TasksCog pick up the patched version
        self.cog = TasksCog(self.bot)
        self.mock_loop_start_method = mock_loop_start_method # Store the AsyncMock

    async def test_dummy(self):
        # A placeholder test to ensure the file is set up correctly
        self.assertTrue(True)
        # Example: Assert that loop was "started" (our immediate version)
        if self.bot.license_check_enabled:
            # Both license_check and cleanup_channels should have their .start() called
            # by the cog's __init__ if license_check_enabled is True.
            # Our mock_loop_start_method (which is Loop.start) should be called twice.
            self.assertEqual(self.mock_loop_start_method.call_count, 2)
        else:
            # Only cleanup_channels.start() is called if license_check_enabled is False.
            self.assertEqual(self.mock_loop_start_method.call_count, 1)


    def _setup_mock_http_response(self, status_code, json_payload=None, exception_to_raise=None):
        """Helper to configure self.bot.http_session.post responses."""
        mock_aiohttp_response = AsyncMock() # This is the object yielded by 'async with ... as resp:'
        mock_aiohttp_response.status = status_code
        if json_payload is not None:
            mock_aiohttp_response.json = AsyncMock(return_value=json_payload)
        # If the response won't have .json() called (e.g. status 500), no need to mock .json

        mock_async_context_manager = AsyncMock() # This is what self.bot.http_session.post() returns
        if exception_to_raise:
            mock_async_context_manager.__aenter__.side_effect = exception_to_raise
        else:
            mock_async_context_manager.__aenter__.return_value = mock_aiohttp_response
        # __aexit__ should also be an AsyncMock; it's called upon exiting the 'async with' block
        mock_async_context_manager.__aexit__ = AsyncMock(return_value=None) # Often returns None or a bool

        self.bot.http_session.post.return_value = mock_async_context_manager


    async def test_license_check_valid_license(self):
        # Setup mock guild and config
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
        # Also check if warning_sent is reset if it was previously sent
        self.bot.db.get_guild_config.return_value['warning_sent'] = 1 # Simulate warning was sent
        await self.cog.license_check() # Call again
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

        # Simulate warning already sent
        self.bot.db.get_guild_config.return_value = {'dkp_channel_id': 67890, 'warning_sent': 1, 'license_status': 'lapsed'}

        self._setup_mock_http_response(status_code=200, json_payload={"status": "lapsed"})

        await self.cog.license_check()

        mock_dkp_channel.send.assert_not_called() # Warning should not be sent again
        self.bot.db.execute.assert_any_call("UPDATE guilds SET license_status = ? WHERE guild_id = ?", ("lapsed", mock_guild.id))
        # Ensure warning_sent = 1 is not called again if it's already 1
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

        self._setup_mock_http_response(status_code=500) # No json_payload needed for error status

        with self.assertLogs(None, level='ERROR') as log: # Capture root logger
            await self.cog.license_check()

        # Check if the specific log message is present
        self.assertTrue(any("Failed to check license. Status: 500" in message for message in log.output),
                        f"Expected log message not found. Logs: {log.output}")

        self.bot.db.execute.assert_not_called() # No DB update on HTTP error


    async def test_license_check_connection_error(self):
        # Test scenario where the HTTP request itself fails (e.g., server down)
        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.id = 12345
        self.bot.guilds = [mock_guild]
        self.bot.db.get_guild_config.return_value = {'dkp_channel_id': 67890, 'warning_sent': 0}

        # Simulate a connection error by having __aenter__ raise an exception
        # Using a standard Python error for simplicity, as the cog catches generic Exception.
        # import aiohttp # aiohttp.ClientError could also be used but might have similar stringification complexities.
        simulated_error = ConnectionError("Simulated connection/network error")
        self._setup_mock_http_response(status_code=None, exception_to_raise=simulated_error)

        with self.assertLogs(None, level='ERROR') as log: # logging.exception logs at ERROR level to root logger
            await self.cog.license_check()

        self.assertTrue(any(f"Error connecting to licensing server at {self.bot.license_server_url}" in message for message in log.output),
                        f"Expected connection error log message not found. Logs: {log.output}")
        self.bot.db.execute.assert_not_called()


    async def test_license_check_no_license_key(self):
        self.bot.license_key = None # No license key
        with self.assertLogs(level='WARNING') as log:
            await self.cog.license_check()
            self.assertTrue(any("No license key found" in message for message in log.output))

        self.bot.http_session.post.assert_not_called()
        self.bot.db.execute.assert_not_called()

    @patch('discord.ext.tasks.Loop.start', new_callable=AsyncMock, side_effect=immediate_loop_side_effect)
    async def test_license_check_disabled_in_cog_init(self, mock_loop_start_override_method):
        # Re-initialize cog with license_check_enabled = False
        self.bot_specific = AsyncMock() # Create a fresh bot mock for this specific test scenario
        self.bot_specific.guilds = []
        self.bot_specific.license_check_enabled = False # Crucial part
        self.bot_specific.http_session = AsyncMock()
        self.bot_specific.db = AsyncMock()
        self.bot_specific.license_key = "test_license_key"
        self.bot_specific.license_server_url = "http://testserver.com"

        cog_disabled = TasksCog(self.bot_specific)

        # Assert that license_check.start() was NOT called, but cleanup_channels.start() was
        # Our mock_loop_start_override_method (which is Loop.start) should be called once for cleanup_channels.
        self.assertEqual(mock_loop_start_override_method.call_count, 1)
        # The call_count == 1 implies that only cleanup_channels.start() was called,
        # as license_check.start() is guarded by an if-statement.
        # Further inspecting call_args can be brittle here if the mock setup for Loop.start is complex.
        # For this test, knowing only one loop started is sufficient.

    async def test_cleanup_channels_empty_raid_vc_deleted(self):
        # Mock an active raid with an empty VC
        mock_vc = AsyncMock(spec=discord.VoiceChannel)
        mock_vc.id = 1001
        mock_vc.name = "Raid VC Alpha"
        mock_vc.members = [] # Empty

        self.bot.db.fetchall.return_value = [{'vc_id': mock_vc.id}]
        self.bot.get_channel.return_value = mock_vc

        await self.cog.cleanup_channels()

        self.bot.db.fetchall.assert_called_once_with("SELECT vc_id FROM raids WHERE is_active = 1")
        self.bot.get_channel.assert_called_once_with(mock_vc.id)
        mock_vc.delete.assert_called_once_with(reason="Automatic cleanup of empty raid channel.")
        # Raids remain active after VC cleanup; no DB update should be made here.
        self.bot.db.execute.assert_not_called()

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
        # No delete call on a None object, no error should be raised by the cog
        self.bot.db.execute.assert_not_called() # DB entry should not be updated

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

        self.bot.db.fetchall.assert_called_once_with("SELECT vc_id FROM raids WHERE is_active = 1")
        self.bot.get_channel.assert_not_called()
        self.bot.db.execute.assert_not_called()


if __name__ == '__main__':
    unittest.main()
