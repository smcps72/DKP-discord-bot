import aiosqlite
import logging
import os

# Allow overriding the database file path via environment variable so that
# production deployments (e.g., Railway) can store the SQLite file on a
# persistent volume. Locally, this will continue to default to "dkp_bot.db"
# in the current working directory.
DB_FILE = os.getenv("DKP_DB_FILE", "dkp_bot.db")

class Database:
    def __init__(self, db_file):
        self.db_file = db_file
        self.pool = None

    async def connect(self):
        self.pool = await aiosqlite.connect(self.db_file)
        # The connection object from aiosqlite.connect can be used like a pool of size 1.
        # For more complex scenarios, a dedicated pool object might be used, but for a single
        # bot process, this is robust.
        self.pool.row_factory = aiosqlite.Row
        await self._create_tables()

    async def _create_tables(self):
        async with self.pool.cursor() as cursor:
            await cursor.execute("""
                CREATE TABLE IF NOT EXISTS guilds (
                    guild_id INTEGER PRIMARY KEY,
                    license_key TEXT,
                    license_status TEXT DEFAULT 'unknown',
                    warning_sent INTEGER DEFAULT 0,
                    dkp_category_id INTEGER,
                    dkp_channel_id INTEGER,
                    raid_channel_id INTEGER,
                    officer_role_id INTEGER,
                    raider_role_id INTEGER,
                    raid_leader_role_id INTEGER,
                    raid_vc_template_id INTEGER,
                    default_dkp_award INTEGER DEFAULT 5
                )
            """)
            await cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER,
                    guild_id INTEGER,
                    dkp INTEGER DEFAULT 0,
                    PRIMARY KEY (user_id, guild_id)
                )
            """)
            await cursor.execute("""
                CREATE TABLE IF NOT EXISTS raids (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER,
                    leader_id INTEGER,
                    vc_id INTEGER,
                    thread_id INTEGER UNIQUE,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    rules TEXT
                )
            """)
            await cursor.execute("""
                CREATE TABLE IF NOT EXISTS raid_members (
                    raid_id INTEGER,
                    user_id INTEGER,
                    PRIMARY KEY (raid_id, user_id),
                    FOREIGN KEY (raid_id) REFERENCES raids(id)
                )
            """)
            await cursor.execute("""
                CREATE TABLE IF NOT EXISTS auctions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    raid_id INTEGER,
                    item_name TEXT,
                    is_active INTEGER DEFAULT 1,
                    highest_bidder_id INTEGER,
                    highest_bid INTEGER DEFAULT 0,
                    message_id INTEGER,
                    FOREIGN KEY (raid_id) REFERENCES raids(id)
                )
            """)
            await cursor.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER,
                    user_id INTEGER,
                    change INTEGER,
                    reason TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await self.pool.commit()

    # Generic execute/fetch methods
    async def execute(self, sql, params=()):
        async with self.pool.execute(sql, params) as cursor:
            await self.pool.commit()

    async def execute_insert(self, sql, params=()):
        """Execute an insert statement and return the last row id."""
        async with self.pool.execute(sql, params) as cursor:
            await self.pool.commit()
            return cursor.lastrowid

    async def fetchone(self, sql, params=()):
        async with self.pool.execute(sql, params) as cursor:
            return await cursor.fetchone()

    async def fetchall(self, sql, params=()):
        async with self.pool.execute(sql, params) as cursor:
            return await cursor.fetchall()

    # ... add specific helper methods as needed below ...
    
    async def get_guild_config(self, guild_id):
        return await self.fetchone("SELECT * FROM guilds WHERE guild_id = ?", (guild_id,))

    async def get_user_dkp(self, user_id, guild_id):
        await self.execute("INSERT OR IGNORE INTO users (user_id, guild_id) VALUES (?, ?)", (user_id, guild_id))
        row = await self.fetchone("SELECT dkp FROM users WHERE user_id = ? AND guild_id = ?", (user_id, guild_id))
        return row['dkp'] if row else 0

    async def modify_user_dkp(self, user_id, guild_id, amount, reason):
        await self.get_user_dkp(user_id, guild_id) # Ensure user exists
        await self.execute("UPDATE users SET dkp = dkp + ? WHERE user_id = ? AND guild_id = ?", (amount, user_id, guild_id))
        await self.execute(
            "INSERT INTO transactions (guild_id, user_id, change, reason) VALUES (?, ?, ?, ?)",
            (guild_id, user_id, amount, reason)
        )
        logging.info(f"Modified DKP for {user_id} by {amount} in {guild_id}. Reason: {reason}")

    async def get_user_transactions(self, guild_id: int, user_id: int, limit: int = 20):
        limit = max(1, min(int(limit), 100))
        return await self.fetchall(
            "SELECT change, reason, timestamp FROM transactions WHERE guild_id = ? AND user_id = ? ORDER BY timestamp DESC LIMIT ?",
            (guild_id, user_id, limit),
        )
    
    async def get_raid_by_thread(self, thread_id):
        return await self.fetchone("SELECT * FROM raids WHERE thread_id = ? AND is_active = 1", (thread_id,))

    async def get_raid_by_vc(self, vc_id):
        return await self.fetchone("SELECT * FROM raids WHERE vc_id = ? AND is_active = 1", (vc_id,))

    async def add_raid_member(self, raid_id: int, user_id: int):
        await self.execute(
            "INSERT OR IGNORE INTO raid_members (raid_id, user_id) VALUES (?, ?)",
            (raid_id, user_id),
        )

    async def get_raid_members(self, raid_id: int):
        return await self.fetchall(
            "SELECT user_id FROM raid_members WHERE raid_id = ?",
            (raid_id,),
        )

    async def get_active_auction(self, raid_id):
        return await self.fetchone("SELECT * FROM auctions WHERE raid_id = ? AND is_active = 1", (raid_id,))

    async def get_raid_rules(self, raid_id: int):
        row = await self.fetchone("SELECT rules FROM raids WHERE id = ?", (raid_id,))
        if row is None:
            return None
        try:
            return row["rules"]
        except (KeyError, TypeError):
            return None

    async def set_raid_rules(self, raid_id: int, rules):
        await self.execute("UPDATE raids SET rules = ? WHERE id = ?", (rules, raid_id))
