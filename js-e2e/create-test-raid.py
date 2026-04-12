"""Create a raid via Discord REST API + local DB for E2E testing.

Usage:
    source venv/bin/activate
    python js-e2e/create-test-raid.py

Prints the thread URL on success.
"""
import asyncio
import json
import os
import sys

import aiohttp
import aiosqlite
import dotenv

dotenv.load_dotenv(os.path.join(os.path.dirname(__file__), '..', 'secrets', '.env.local'))

BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN')  # Primary "DKP-local" bot — has channel permissions
GUILD_ID = 1388467074346516621
ACTIVE_RAIDS_CHANNEL_ID = 1477500243301105756
# Use the test user as raid leader so the control panel shows leader buttons
TEST_USER_ID = 1455353368468914379  # play_dkp_06761
DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'dkp_bot.db')

API = 'https://discord.com/api/v10'
HEADERS = {
    'Authorization': f'Bot {BOT_TOKEN}',
    'Content-Type': 'application/json',
}


async def main():
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        # 1. Send announcement message
        msg_payload = {
            'content': f"Raid 'E2E-Undo-Test' started by <@{TEST_USER_ID}> (automated E2E setup)",
        }
        async with session.post(f'{API}/channels/{ACTIVE_RAIDS_CHANNEL_ID}/messages', json=msg_payload) as resp:
            if resp.status != 200:
                print(f'Failed to send message: {resp.status} {await resp.text()}', file=sys.stderr)
                sys.exit(1)
            msg = await resp.json()
            msg_id = msg['id']

        # 2. Create a thread from the message
        thread_payload = {
            'name': 'E2E-Undo-Test - Raid Log',
            'auto_archive_duration': 1440,
        }
        async with session.post(f'{API}/channels/{ACTIVE_RAIDS_CHANNEL_ID}/messages/{msg_id}/threads', json=thread_payload) as resp:
            if resp.status not in (200, 201):
                print(f'Failed to create thread: {resp.status} {await resp.text()}', file=sys.stderr)
                sys.exit(1)
            thread = await resp.json()
            thread_id = thread['id']

        # 3. Send the "Open Raid Control Panel" button message in the thread
        panel_payload = {
            'embeds': [{
                'title': 'Raid Control Panel',
                'description': 'Click the button below to open your control panel (ephemeral).',
                'color': 0x3498db,
            }],
            'components': [{
                'type': 1,  # ActionRow
                'components': [{
                    'type': 2,  # Button
                    'style': 1,  # Primary
                    'label': 'Open Raid Control Panel',
                    'custom_id': 'raid_open_panel',
                }],
            }],
        }
        async with session.post(f'{API}/channels/{thread_id}/messages', json=panel_payload) as resp:
            if resp.status != 200:
                print(f'Failed to send panel: {resp.status} {await resp.text()}', file=sys.stderr)
                sys.exit(1)

        # 4. Send jump link message
        jump_payload = {
            'content': f'Jump to the current raid log thread: <#{thread_id}>',
        }
        async with session.post(f'{API}/channels/{ACTIVE_RAIDS_CHANNEL_ID}/messages', json=jump_payload) as resp:
            pass  # best-effort

    # 5. Insert raid row into database
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            'INSERT INTO raids (guild_id, leader_id, vc_id, thread_id, announcement_message_id, is_active) '
            'VALUES (?, ?, NULL, ?, ?, 1)',
            (GUILD_ID, TEST_USER_ID, int(thread_id), int(msg_id)),
        )
        await db.commit()
        cursor = await db.execute('SELECT id FROM raids WHERE thread_id = ?', (int(thread_id),))
        row = await cursor.fetchone()
        raid_id = row[0] if row else '?'

    thread_url = f'https://discord.com/channels/{GUILD_ID}/{thread_id}'
    print(f'raid_id={raid_id}')
    print(f'thread_id={thread_id}')
    print(f'thread_url={thread_url}')


if __name__ == '__main__':
    asyncio.run(main())
