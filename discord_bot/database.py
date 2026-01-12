import aiosqlite
import logging
import os
import asyncio

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
        await self._migrate_schema()

    async def _migrate_schema(self):
        async with self.pool.execute("PRAGMA table_info(guilds)") as cursor:
            rows = await cursor.fetchall()
        existing = {row[1] for row in rows}

        migrations: list[tuple[str, str]] = [
            ("license_key", "ALTER TABLE guilds ADD COLUMN license_key TEXT"),
            (
                "license_status",
                "ALTER TABLE guilds ADD COLUMN license_status TEXT DEFAULT 'unknown'",
            ),
            (
                "warning_sent",
                "ALTER TABLE guilds ADD COLUMN warning_sent INTEGER DEFAULT 0",
            ),
            ("dkp_category_id", "ALTER TABLE guilds ADD COLUMN dkp_category_id INTEGER"),
            ("dkp_channel_id", "ALTER TABLE guilds ADD COLUMN dkp_channel_id INTEGER"),
            ("raid_channel_id", "ALTER TABLE guilds ADD COLUMN raid_channel_id INTEGER"),
            (
                "completed_raid_channel_id",
                "ALTER TABLE guilds ADD COLUMN completed_raid_channel_id INTEGER",
            ),
            ("admin_role_id", "ALTER TABLE guilds ADD COLUMN admin_role_id INTEGER"),
            ("officer_role_id", "ALTER TABLE guilds ADD COLUMN officer_role_id INTEGER"),
            ("raider_role_id", "ALTER TABLE guilds ADD COLUMN raider_role_id INTEGER"),
            (
                "raid_leader_role_id",
                "ALTER TABLE guilds ADD COLUMN raid_leader_role_id INTEGER",
            ),
            (
                "raid_vc_template_id",
                "ALTER TABLE guilds ADD COLUMN raid_vc_template_id INTEGER",
            ),
            (
                "default_dkp_award",
                "ALTER TABLE guilds ADD COLUMN default_dkp_award INTEGER DEFAULT 5",
            ),
            (
                "archive_category_id",
                "ALTER TABLE guilds ADD COLUMN archive_category_id INTEGER",
            ),
        ]

        for col, sql in migrations:
            if col in existing:
                continue
            try:
                await self.pool.execute(sql)
            except aiosqlite.OperationalError:
                continue

        async with self.pool.execute("PRAGMA table_info(raids)") as cursor:
            raid_rows = await cursor.fetchall()
        raid_existing = {row[1] for row in raid_rows}

        raid_migrations: list[tuple[str, str]] = [
            (
                "announcement_message_id",
                "ALTER TABLE raids ADD COLUMN announcement_message_id INTEGER",
            ),
        ]

        for col, sql in raid_migrations:
            if col in raid_existing:
                continue
            try:
                await self.pool.execute(sql)
            except aiosqlite.OperationalError:
                continue
        await self.pool.commit()

    async def _create_tables(self):
        async with self.pool.cursor() as cursor:
            await cursor.execute("""
                CREATE TABLE IF NOT EXISTS guilds (
                    guild_id INTEGER PRIMARY KEY,
                    license_key TEXT,
                    license_status TEXT DEFAULT 'unknown',
                    warning_sent INTEGER DEFAULT 0,
                    dkp_category_id INTEGER,
                    archive_category_id INTEGER,
                    dkp_channel_id INTEGER,
                    raid_channel_id INTEGER,
                    completed_raid_channel_id INTEGER,
                    admin_role_id INTEGER,
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
                    announcement_message_id INTEGER,
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
                CREATE TABLE IF NOT EXISTS raid_join_requests (
                    raid_id INTEGER,
                    user_id INTEGER,
                    status TEXT DEFAULT 'pending',
                    source TEXT,
                    requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    decided_at TIMESTAMP,
                    decided_by INTEGER,
                    PRIMARY KEY (raid_id, user_id),
                    FOREIGN KEY (raid_id) REFERENCES raids(id)
                )
            """)
            await cursor.execute("""
                CREATE TABLE IF NOT EXISTS raid_member_exclusions (
                    raid_id INTEGER,
                    user_id INTEGER,
                    excluded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (raid_id, user_id),
                    FOREIGN KEY (raid_id) REFERENCES raids(id)
                )
            """)
            await cursor.execute("""
                CREATE TABLE IF NOT EXISTS raid_member_groups (
                    raid_id INTEGER,
                    user_id INTEGER,
                    group_number INTEGER,
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
                CREATE TABLE IF NOT EXISTS auction_bids (
                    auction_id INTEGER,
                    user_id INTEGER,
                    amount INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (auction_id, user_id),
                    FOREIGN KEY (auction_id) REFERENCES auctions(id)
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
        attempts = 3
        delay = 0.2
        for attempt in range(attempts):
            try:
                async with self.pool.execute(sql, params) as cursor:
                    await self.pool.commit()
                return
            except (aiosqlite.OperationalError, OSError) as e:
                if attempt == attempts - 1:
                    logging.error("DB execute failed after %s attempts: %s", attempts, e)
                    raise
                logging.warning(
                    "Transient DB execute error (attempt %s/%s): %s",
                    attempt + 1,
                    attempts,
                    e,
                )
                await asyncio.sleep(delay)
                delay *= 2

    async def add_raid_member_exclusion(self, raid_id: int, user_id: int):
        await self.execute(
            "INSERT OR IGNORE INTO raid_member_exclusions (raid_id, user_id) VALUES (?, ?)",
            (raid_id, user_id),
        )

    async def remove_raid_member_exclusion(self, raid_id: int, user_id: int):
        await self.execute(
            "DELETE FROM raid_member_exclusions WHERE raid_id = ? AND user_id = ?",
            (raid_id, user_id),
        )

    async def is_raid_member_excluded(self, raid_id: int, user_id: int) -> bool:
        row = await self.fetchone(
            "SELECT 1 FROM raid_member_exclusions WHERE raid_id = ? AND user_id = ?",
            (raid_id, user_id),
        )
        return row is not None

    async def set_raid_member_group(self, raid_id: int, user_id: int, group_number: int | None):
        if group_number is None:
            await self.execute(
                "DELETE FROM raid_member_groups WHERE raid_id = ? AND user_id = ?",
                (raid_id, user_id),
            )
            return
        await self.execute(
            """
            INSERT INTO raid_member_groups (raid_id, user_id, group_number)
            VALUES (?, ?, ?)
            ON CONFLICT(raid_id, user_id)
            DO UPDATE SET group_number = excluded.group_number
            """,
            (raid_id, user_id, int(group_number)),
        )

    async def get_raid_member_groups(self, raid_id: int):
        return await self.fetchall(
            "SELECT user_id, group_number FROM raid_member_groups WHERE raid_id = ?",
            (raid_id,),
        )

    async def remove_raid_member(self, raid_id: int, user_id: int) -> bool:
        attempts = 3
        delay = 0.2
        for attempt in range(attempts):
            try:
                async with self.pool.execute(
                    "DELETE FROM raid_members WHERE raid_id = ? AND user_id = ?",
                    (raid_id, user_id),
                ) as cursor:
                    await self.pool.commit()
                    try:
                        return int(cursor.rowcount) > 0
                    except Exception:
                        return False
            except (aiosqlite.OperationalError, OSError) as e:
                if attempt == attempts - 1:
                    logging.error("DB remove_raid_member failed after %s attempts: %s", attempts, e)
                    raise
                logging.warning(
                    "Transient DB remove_raid_member error (attempt %s/%s): %s",
                    attempt + 1,
                    attempts,
                    e,
                )
                await asyncio.sleep(delay)
                delay *= 2

    async def get_raid_join_request(self, raid_id: int, user_id: int):
        return await self.fetchone(
            "SELECT * FROM raid_join_requests WHERE raid_id = ? AND user_id = ?",
            (raid_id, user_id),
        )

    async def delete_raid_join_request(self, raid_id: int, user_id: int):
        await self.execute(
            "DELETE FROM raid_join_requests WHERE raid_id = ? AND user_id = ?",
            (raid_id, user_id),
        )

    async def upsert_raid_join_request(self, raid_id: int, user_id: int, source: str | None = None):
        await self.execute(
            """
            INSERT INTO raid_join_requests (raid_id, user_id, status, source)
            VALUES (?, ?, 'pending', ?)
            ON CONFLICT(raid_id, user_id)
            DO UPDATE SET status = 'pending', source = excluded.source, requested_at = CURRENT_TIMESTAMP, decided_at = NULL, decided_by = NULL
            """,
            (raid_id, user_id, source),
        )

    async def set_raid_join_request_status(
        self,
        raid_id: int,
        user_id: int,
        status: str,
        decided_by: int | None = None,
    ):
        await self.execute(
            """
            UPDATE raid_join_requests
            SET status = ?, decided_at = CURRENT_TIMESTAMP, decided_by = ?
            WHERE raid_id = ? AND user_id = ?
            """,
            (status, decided_by, raid_id, user_id),
        )

    async def execute_insert(self, sql, params=()):
        """Execute an insert statement and return the last row id."""
        attempts = 3
        delay = 0.2
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                async with self.pool.execute(sql, params) as cursor:
                    await self.pool.commit()
                    return cursor.lastrowid
            except (aiosqlite.OperationalError, OSError) as e:
                last_error = e
                if attempt == attempts - 1:
                    logging.error("DB insert failed after %s attempts: %s", attempts, e)
                    raise
                logging.warning(
                    "Transient DB insert error (attempt %s/%s): %s",
                    attempt + 1,
                    attempts,
                    e,
                )
                await asyncio.sleep(delay)
                delay *= 2

    async def fetchone(self, sql, params=()):
        attempts = 3
        delay = 0.2
        for attempt in range(attempts):
            try:
                async with self.pool.execute(sql, params) as cursor:
                    return await cursor.fetchone()
            except (aiosqlite.OperationalError, OSError) as e:
                if attempt == attempts - 1:
                    logging.error("DB fetchone failed after %s attempts: %s", attempts, e)
                    raise
                logging.warning(
                    "Transient DB fetchone error (attempt %s/%s): %s",
                    attempt + 1,
                    attempts,
                    e,
                )
                await asyncio.sleep(delay)
                delay *= 2

    async def fetchall(self, sql, params=()):
        attempts = 3
        delay = 0.2
        for attempt in range(attempts):
            try:
                async with self.pool.execute(sql, params) as cursor:
                    return await cursor.fetchall()
            except (aiosqlite.OperationalError, OSError) as e:
                if attempt == attempts - 1:
                    logging.error("DB fetchall failed after %s attempts: %s", attempts, e)
                    raise
                logging.warning(
                    "Transient DB fetchall error (attempt %s/%s): %s",
                    attempt + 1,
                    attempts,
                    e,
                )
                await asyncio.sleep(delay)
                delay *= 2

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

    async def get_active_raid_by_leader(self, guild_id: int, leader_id: int):
        return await self.fetchone(
            "SELECT * FROM raids WHERE guild_id = ? AND leader_id = ? AND is_active = 1 ORDER BY created_at DESC LIMIT 1",
            (guild_id, leader_id),
        )

    async def add_raid_member(self, raid_id: int, user_id: int):
        attempts = 3
        delay = 0.2
        for attempt in range(attempts):
            try:
                async with self.pool.execute(
                    "INSERT OR IGNORE INTO raid_members (raid_id, user_id) VALUES (?, ?)",
                    (raid_id, user_id),
                ) as cursor:
                    await self.pool.commit()
                    try:
                        return int(cursor.rowcount) > 0
                    except Exception:
                        return False
            except (aiosqlite.OperationalError, OSError) as e:
                if attempt == attempts - 1:
                    logging.error("DB add_raid_member failed after %s attempts: %s", attempts, e)
                    raise
                logging.warning(
                    "Transient DB add_raid_member error (attempt %s/%s): %s",
                    attempt + 1,
                    attempts,
                    e,
                )
                await asyncio.sleep(delay)
                delay *= 2

    async def get_raid_members(self, raid_id: int):
        return await self.fetchall(
            "SELECT user_id FROM raid_members WHERE raid_id = ?",
            (raid_id,),
        )

    async def is_raid_member(self, raid_id: int, user_id: int) -> bool:
        row = await self.fetchone(
            "SELECT 1 FROM raid_members WHERE raid_id = ? AND user_id = ?",
            (raid_id, user_id),
        )
        return row is not None

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

    async def get_user_auction_bid(self, auction_id: int, user_id: int):
        return await self.fetchone(
            "SELECT amount FROM auction_bids WHERE auction_id = ? AND user_id = ?",
            (auction_id, user_id),
        )

    async def record_auction_bid(self, auction_id: int, user_id: int, amount: int):
        await self.execute(
            "INSERT OR IGNORE INTO auction_bids (auction_id, user_id, amount) VALUES (?, ?, ?)",
            (auction_id, user_id, amount),
        )
