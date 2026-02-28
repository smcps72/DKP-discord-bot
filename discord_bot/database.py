import aiosqlite
import logging
import os
import asyncio

# Allow overriding the database file path via environment variable so that
# production deployments (e.g., Railway) can store the SQLite file on a
# persistent volume. Locally, this will continue to default to "dkp_bot.db"
# in the current working directory.
_railway_env = os.getenv("RAILWAY_ENVIRONMENT_NAME") or os.getenv("RAILWAY_ENVIRONMENT")
_railway_service = os.getenv("RAILWAY_SERVICE_NAME")
_db_dir = os.getenv("DKP_DB_DIR")
if _db_dir:
    try:
        os.makedirs(_db_dir, exist_ok=True)
    except Exception:
        pass

_safe_env = "".join([c if (c.isalnum() or c in ("-", "_")) else "_" for c in str(_railway_env)]) if _railway_env else ""
_safe_service = "".join([c if (c.isalnum() or c in ("-", "_")) else "_" for c in str(_railway_service)]) if _railway_service else ""
_railway_suffix = f"_{_safe_env}" + (f"_{_safe_service}" if _safe_service else "") if _safe_env else ""

def _apply_suffix(path: str) -> str:
    if not _railway_suffix:
        return path
    base = os.path.basename(path)
    if _railway_suffix in base:
        return path
    stem, ext = os.path.splitext(base)
    if not ext:
        ext = ".db"
    return os.path.join(os.path.dirname(path), f"{stem}{_railway_suffix}{ext}")

_db_override = os.getenv("DKP_DB_FILE")
if _db_override:
    raw = str(_db_override).strip()
    raw = raw.replace('"', "").replace("'", "")
    if not raw:
        raw = "dkp_bot.db"
    if _db_dir and not os.path.isabs(raw):
        raw = os.path.join(_db_dir, raw)
    DB_FILE = _apply_suffix(raw)
elif _railway_env:
    filename = f"dkp_bot{_railway_suffix}.db" if _railway_suffix else "dkp_bot.db"
    raw = os.path.join(_db_dir, filename) if _db_dir else filename
    DB_FILE = raw
else:
    DB_FILE = os.path.join(_db_dir, "dkp_bot.db") if _db_dir else "dkp_bot.db"

class Database:
    def __init__(self, db_file):
        self.db_file = db_file
        self.pool = None

    def _should_reconnect(self, err: Exception) -> bool:
        msg = str(err).lower()
        return (
            "attempt to write a readonly database" in msg
            or "readonly database" in msg
            or "unable to open database file" in msg
            or "disk i/o error" in msg
        )

    async def close(self):
        if getattr(self, "pool", None) is None:
            return
        try:
            await self.pool.close()
        finally:
            self.pool = None

    async def reconnect(self):
        await self.close()
        await self.connect()

    async def connect(self):
        if getattr(self, "pool", None) is not None:
            try:
                await self.pool.close()
            except Exception:
                pass
            self.pool = None

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
                "ALTER TABLE guilds ADD COLUMN default_dkp_award INTEGER DEFAULT 10",
            ),
            (
                "archive_category_id",
                "ALTER TABLE guilds ADD COLUMN archive_category_id INTEGER",
            ),
            (
                "raid_member_list_order",
                "ALTER TABLE guilds ADD COLUMN raid_member_list_order TEXT DEFAULT 'name'",
            ),
            (
                "last_announced_version",
                "ALTER TABLE guilds ADD COLUMN last_announced_version TEXT",
            ),
            (
                "default_dkp_interval",
                "ALTER TABLE guilds ADD COLUMN default_dkp_interval INTEGER DEFAULT 1",
            ),
            (
                "guild_bank_channel_id",
                "ALTER TABLE guilds ADD COLUMN guild_bank_channel_id INTEGER",
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
            (
                "group_count",
                "ALTER TABLE raids ADD COLUMN group_count INTEGER",
            ),
            (
                "group_panel_message_id",
                "ALTER TABLE raids ADD COLUMN group_panel_message_id INTEGER",
            ),
            (
                "auto_add_from_vc",
                "ALTER TABLE raids ADD COLUMN auto_add_from_vc INTEGER DEFAULT 0",
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
                    default_dkp_award INTEGER DEFAULT 10,
                    default_dkp_interval INTEGER DEFAULT 1,
                    raid_member_list_order TEXT DEFAULT 'name',
                    last_announced_version TEXT,
                    guild_bank_channel_id INTEGER
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
                    group_count INTEGER,
                    group_panel_message_id INTEGER,
                    auto_add_from_vc INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    rules TEXT
                )
            """)
            await cursor.execute("""
                CREATE TABLE IF NOT EXISTS raid_voice_channels (
                    raid_id INTEGER,
                    vc_id INTEGER,
                    PRIMARY KEY (raid_id, vc_id),
                    FOREIGN KEY (raid_id) REFERENCES raids(id)
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
                CREATE TABLE IF NOT EXISTS raid_member_history (
                    raid_id INTEGER,
                    user_id INTEGER,
                    first_joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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
                    reason TEXT DEFAULT 'manual',
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
                CREATE TABLE IF NOT EXISTS raid_group_settings (
                    raid_id INTEGER PRIMARY KEY,
                    group_count INTEGER NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (raid_id) REFERENCES raids(id)
                )
            """)
            await cursor.execute("""
                CREATE TABLE IF NOT EXISTS raid_timed_awards (
                    raid_id INTEGER PRIMARY KEY,
                    amount INTEGER NOT NULL,
                    interval_minutes INTEGER NOT NULL,
                    is_enabled INTEGER DEFAULT 1,
                    last_awarded_at TIMESTAMP,
                    FOREIGN KEY (raid_id) REFERENCES raids(id)
                )
            """)
            await cursor.execute("""
                CREATE TABLE IF NOT EXISTS raid_voice_absences (
                    raid_id INTEGER,
                    user_id INTEGER,
                    absent_since TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (raid_id, user_id),
                    FOREIGN KEY (raid_id) REFERENCES raids(id)
                )
            """)
            await cursor.execute("""
                CREATE TABLE IF NOT EXISTS raid_leader_absences (
                    raid_id INTEGER PRIMARY KEY,
                    absent_since TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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

            await cursor.execute("""
                CREATE TABLE IF NOT EXISTS raid_dkp_transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    raid_id INTEGER NOT NULL,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    change INTEGER NOT NULL,
                    reason TEXT,
                    actor_id INTEGER,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (raid_id) REFERENCES raids(id)
                )
            """)
            await cursor.execute("""
                CREATE TABLE IF NOT EXISTS guild_bank_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    item_name TEXT NOT NULL,
                    quantity INTEGER NOT NULL DEFAULT 0,
                    category TEXT DEFAULT 'other',
                    location TEXT DEFAULT '',
                    held_by_user_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await cursor.execute("""
                CREATE TABLE IF NOT EXISTS guild_bank_transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    item_id INTEGER,
                    item_name TEXT NOT NULL,
                    action TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    category TEXT DEFAULT 'other',
                    location TEXT DEFAULT '',
                    held_by_user_id INTEGER,
                    actor_id INTEGER NOT NULL,
                    note TEXT DEFAULT '',
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (item_id) REFERENCES guild_bank_items(id)
                )
            """)
            await self.pool.commit()

    # Generic execute/fetch methods
    async def execute(self, sql, params=()):
        attempts = 3
        delay = 0.2
        did_reconnect = False
        for attempt in range(attempts):
            try:
                async with self.pool.execute(sql, params) as cursor:
                    await self.pool.commit()
                return
            except (aiosqlite.OperationalError, OSError) as e:
                if not did_reconnect and self._should_reconnect(e):
                    did_reconnect = True
                    logging.warning("DB execute error suggests stale/readonly connection; reconnecting: %s", e)
                    try:
                        await self.reconnect()
                        continue
                    except Exception:
                        logging.exception("DB reconnect failed")
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

    async def add_raid_member_exclusion(self, raid_id: int, user_id: int, reason: str = "manual"):
        """Add an exclusion. reason should be 'manual', 'inactivity', or 'voluntary'."""
        await self.execute(
            "INSERT INTO raid_member_exclusions (raid_id, user_id, reason) VALUES (?, ?, ?) ON CONFLICT(raid_id, user_id) DO UPDATE SET reason = excluded.reason, excluded_at = CURRENT_TIMESTAMP",
            (raid_id, user_id, reason),
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

    async def get_raid_member_exclusion_reason(self, raid_id: int, user_id: int) -> str | None:
        """Get the exclusion reason for a user. Returns 'manual', 'inactivity', 'voluntary', or None if not excluded."""
        row = await self.fetchone(
            "SELECT reason FROM raid_member_exclusions WHERE raid_id = ? AND user_id = ?",
            (raid_id, user_id),
        )
        if row is None:
            return None
        return row["reason"] if row["reason"] else "manual"

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

    async def clear_all_raid_member_groups(self, raid_id: int) -> int:
        """Clear all group assignments for a raid. Returns the number of rows deleted."""
        result = await self.execute(
            "DELETE FROM raid_member_groups WHERE raid_id = ?",
            (raid_id,),
        )
        return result.rowcount if hasattr(result, "rowcount") else 0

    async def get_raid_group_count(self, raid_id: int) -> int | None:
        raid_id_int = int(raid_id)

        row = await self.fetchone(
            "SELECT group_count FROM raid_group_settings WHERE raid_id = ?",
            (raid_id_int,),
        )
        if row is not None:
            try:
                count = int(row["group_count"])
                return count if count > 0 else None
            except Exception:
                pass

        # Back-compat: older installs and some flows store group_count on the raids row.
        row = await self.fetchone(
            "SELECT group_count FROM raids WHERE id = ?",
            (raid_id_int,),
        )
        if row is None:
            return None
        try:
            count = int(row["group_count"])
            return count if count > 0 else None
        except Exception:
            return None

    async def set_raid_group_count(self, raid_id: int, group_count: int | None):
        if group_count is None:
            await self.execute(
                "DELETE FROM raid_group_settings WHERE raid_id = ?",
                (int(raid_id),),
            )
            try:
                await self.execute(
                    "UPDATE raids SET group_count = 0 WHERE id = ?",
                    (int(raid_id),),
                )
            except Exception:
                pass
            return

        await self.execute(
            """
            INSERT INTO raid_group_settings (raid_id, group_count)
            VALUES (?, ?)
            ON CONFLICT(raid_id)
            DO UPDATE SET group_count = excluded.group_count, updated_at = CURRENT_TIMESTAMP
            """,
            (int(raid_id), int(group_count)),
        )

        try:
            await self.execute(
                "UPDATE raids SET group_count = ? WHERE id = ?",
                (int(group_count), int(raid_id)),
            )
        except Exception:
            pass

    async def get_raid_timed_award(self, raid_id: int):
        return await self.fetchone(
            "SELECT raid_id, amount, interval_minutes, is_enabled, last_awarded_at FROM raid_timed_awards WHERE raid_id = ?",
            (int(raid_id),),
        )

    async def set_raid_timed_award(
        self,
        raid_id: int,
        amount: int,
        interval_minutes: int,
        is_enabled: bool = True,
    ):
        await self.execute(
            """
            INSERT INTO raid_timed_awards (raid_id, amount, interval_minutes, is_enabled, last_awarded_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(raid_id)
            DO UPDATE SET
                amount = excluded.amount,
                interval_minutes = excluded.interval_minutes,
                is_enabled = excluded.is_enabled,
                last_awarded_at = CURRENT_TIMESTAMP
            """,
            (int(raid_id), int(amount), int(interval_minutes), 1 if is_enabled else 0),
        )

    async def set_raid_timed_award_enabled(self, raid_id: int, is_enabled: bool):
        if is_enabled:
            await self.execute(
                "UPDATE raid_timed_awards SET is_enabled = 1, last_awarded_at = CURRENT_TIMESTAMP WHERE raid_id = ?",
                (int(raid_id),),
            )
            return
        await self.execute(
            "UPDATE raid_timed_awards SET is_enabled = 0 WHERE raid_id = ?",
            (int(raid_id),),
        )

    async def remove_raid_member(self, raid_id: int, user_id: int) -> bool:
        attempts = 3
        delay = 0.2
        did_reconnect = False
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
                if not did_reconnect and self._should_reconnect(e):
                    did_reconnect = True
                    logging.warning(
                        "DB remove_raid_member error suggests stale/readonly connection; reconnecting: %s",
                        e,
                    )
                    try:
                        await self.reconnect()
                        continue
                    except Exception:
                        logging.exception("DB reconnect failed")
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
        did_reconnect = False
        for attempt in range(attempts):
            try:
                async with self.pool.execute(sql, params) as cursor:
                    await self.pool.commit()
                    return cursor.lastrowid
            except (aiosqlite.OperationalError, OSError) as e:
                last_error = e
                if not did_reconnect and self._should_reconnect(e):
                    did_reconnect = True
                    logging.warning("DB insert error suggests stale/readonly connection; reconnecting: %s", e)
                    try:
                        await self.reconnect()
                        continue
                    except Exception:
                        logging.exception("DB reconnect failed")
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
        did_reconnect = False
        for attempt in range(attempts):
            try:
                async with self.pool.execute(sql, params) as cursor:
                    return await cursor.fetchone()
            except (aiosqlite.OperationalError, OSError) as e:
                if not did_reconnect and self._should_reconnect(e):
                    did_reconnect = True
                    logging.warning("DB fetchone error suggests stale/readonly connection; reconnecting: %s", e)
                    try:
                        await self.reconnect()
                        continue
                    except Exception:
                        logging.exception("DB reconnect failed")
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
        did_reconnect = False
        for attempt in range(attempts):
            try:
                async with self.pool.execute(sql, params) as cursor:
                    return await cursor.fetchall()
            except (aiosqlite.OperationalError, OSError) as e:
                if not did_reconnect and self._should_reconnect(e):
                    did_reconnect = True
                    logging.warning("DB fetchall error suggests stale/readonly connection; reconnecting: %s", e)
                    try:
                        await self.reconnect()
                        continue
                    except Exception:
                        logging.exception("DB reconnect failed")
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
        return await self.fetchone(
            """
            SELECT r.*
            FROM raids r
            WHERE r.is_active = 1
              AND (
                r.vc_id = ?
                OR EXISTS (
                    SELECT 1
                    FROM raid_voice_channels rvc
                    WHERE rvc.raid_id = r.id AND rvc.vc_id = ?
                )
              )
            ORDER BY r.created_at DESC
            LIMIT 1
            """,
            (vc_id, vc_id),
        )

    async def get_active_raid_by_leader(self, guild_id: int, leader_id: int):
        return await self.fetchone(
            "SELECT * FROM raids WHERE guild_id = ? AND leader_id = ? AND is_active = 1 ORDER BY created_at DESC LIMIT 1",
            (guild_id, leader_id),
        )

    async def add_raid_member(self, raid_id: int, user_id: int):
        attempts = 3
        delay = 0.2
        did_reconnect = False
        for attempt in range(attempts):
            try:
                async with self.pool.execute(
                    "INSERT OR IGNORE INTO raid_members (raid_id, user_id) VALUES (?, ?)",
                    (raid_id, user_id),
                ) as cursor:
                    await self.pool.commit()
                    try:
                        await self.pool.execute(
                            "INSERT OR IGNORE INTO raid_member_history (raid_id, user_id) VALUES (?, ?)",
                            (int(raid_id), int(user_id)),
                        )
                        await self.pool.execute(
                            "UPDATE raid_member_history SET last_joined_at = CURRENT_TIMESTAMP WHERE raid_id = ? AND user_id = ?",
                            (int(raid_id), int(user_id)),
                        )
                        await self.pool.commit()
                    except Exception:
                        pass
                    try:
                        return int(cursor.rowcount) > 0
                    except Exception:
                        return False
            except (aiosqlite.OperationalError, OSError) as e:
                if not did_reconnect and self._should_reconnect(e):
                    did_reconnect = True
                    logging.warning(
                        "DB add_raid_member error suggests stale/readonly connection; reconnecting: %s",
                        e,
                    )
                    try:
                        await self.reconnect()
                        continue
                    except Exception:
                        logging.exception("DB reconnect failed")
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

    async def get_raid_member_history_user_ids(self, raid_id: int):
        rows = await self.fetchall(
            "SELECT user_id FROM raid_member_history WHERE raid_id = ?",
            (int(raid_id),),
        )
        out: list[int] = []
        for r in list(rows or []):
            try:
                out.append(int(r["user_id"]))
            except Exception:
                continue
        return out

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

    async def add_raid_voice_channel(self, raid_id: int, vc_id: int):
        await self.execute(
            "INSERT OR IGNORE INTO raid_voice_channels (raid_id, vc_id) VALUES (?, ?)",
            (int(raid_id), int(vc_id)),
        )

    async def remove_raid_voice_channel(self, raid_id: int, vc_id: int):
        await self.execute(
            "DELETE FROM raid_voice_channels WHERE raid_id = ? AND vc_id = ?",
            (int(raid_id), int(vc_id)),
        )

    async def get_raid_voice_channels(self, raid_id: int):
        return await self.fetchall(
            "SELECT vc_id FROM raid_voice_channels WHERE raid_id = ?",
            (int(raid_id),),
        )

    async def record_raid_dkp_transaction(
        self,
        raid_id: int,
        guild_id: int,
        user_id: int,
        change: int,
        reason: str,
        actor_id: int | None = None,
    ):
        await self.execute(
            """
            INSERT INTO raid_dkp_transactions (raid_id, guild_id, user_id, change, reason, actor_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (int(raid_id), int(guild_id), int(user_id), int(change), str(reason), int(actor_id) if actor_id is not None else None),
        )

    async def get_raid_dkp_totals(self, raid_id: int):
        return await self.fetchall(
            """
            SELECT user_id, COALESCE(SUM(change), 0) AS raid_dkp
            FROM raid_dkp_transactions
            WHERE raid_id = ?
            GROUP BY user_id
            """,
            (int(raid_id),),
        )

    async def get_raid_dkp_participant_user_ids(self, raid_id: int) -> list[int]:
        rows = await self.fetchall(
            """
            SELECT DISTINCT user_id
            FROM raid_dkp_transactions
            WHERE raid_id = ?
            """,
            (int(raid_id),),
        )
        out: list[int] = []
        for r in list(rows or []):
            try:
                out.append(int(r["user_id"]))
            except Exception:
                continue
        return out

    # ---- Guild Bank helpers ----

    async def guild_bank_deposit(
        self,
        guild_id: int,
        item_name: str,
        quantity: int,
        category: str,
        location: str,
        held_by_user_id: int,
        actor_id: int,
        note: str = "",
    ) -> int:
        """Deposit an item into the guild bank. Returns the item row id."""
        existing = await self.fetchone(
            """
            SELECT id, quantity FROM guild_bank_items
            WHERE guild_id = ? AND item_name = ? COLLATE NOCASE
              AND category = ? AND location = ? AND held_by_user_id = ?
            """,
            (int(guild_id), item_name, category, location, int(held_by_user_id)),
        )
        if existing:
            item_id = int(existing["id"])
            new_qty = int(existing["quantity"]) + int(quantity)
            await self.execute(
                "UPDATE guild_bank_items SET quantity = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (new_qty, item_id),
            )
        else:
            item_id = await self.execute_insert(
                """
                INSERT INTO guild_bank_items
                    (guild_id, item_name, quantity, category, location, held_by_user_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (int(guild_id), item_name, int(quantity), category, location, int(held_by_user_id)),
            )

        await self.execute_insert(
            """
            INSERT INTO guild_bank_transactions
                (guild_id, item_id, item_name, action, quantity, category, location, held_by_user_id, actor_id, note)
            VALUES (?, ?, ?, 'deposit', ?, ?, ?, ?, ?, ?)
            """,
            (int(guild_id), item_id, item_name, int(quantity), category, location, int(held_by_user_id), int(actor_id), note),
        )
        return item_id

    async def guild_bank_withdraw(
        self,
        guild_id: int,
        item_id: int,
        quantity: int,
        actor_id: int,
        note: str = "",
    ) -> bool:
        """Withdraw quantity from a guild bank item. Returns True on success."""
        item = await self.fetchone(
            "SELECT * FROM guild_bank_items WHERE id = ? AND guild_id = ?",
            (int(item_id), int(guild_id)),
        )
        if not item:
            return False
        current_qty = int(item["quantity"])
        if quantity > current_qty:
            return False

        new_qty = current_qty - quantity
        if new_qty <= 0:
            await self.execute("DELETE FROM guild_bank_items WHERE id = ?", (int(item_id),))
        else:
            await self.execute(
                "UPDATE guild_bank_items SET quantity = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (new_qty, int(item_id)),
            )

        await self.execute_insert(
            """
            INSERT INTO guild_bank_transactions
                (guild_id, item_id, item_name, action, quantity, category, location, held_by_user_id, actor_id, note)
            VALUES (?, ?, ?, 'withdraw', ?, ?, ?, ?, ?, ?)
            """,
            (
                int(guild_id),
                int(item_id),
                item["item_name"],
                int(quantity),
                item["category"],
                item["location"],
                item["held_by_user_id"],
                int(actor_id),
                note,
            ),
        )
        return True

    async def guild_bank_get_inventory(self, guild_id: int):
        """Get all items in the guild bank with quantity > 0."""
        return await self.fetchall(
            """
            SELECT * FROM guild_bank_items
            WHERE guild_id = ? AND quantity > 0
            ORDER BY category, item_name
            """,
            (int(guild_id),),
        )

    async def guild_bank_get_item(self, item_id: int, guild_id: int):
        return await self.fetchone(
            "SELECT * FROM guild_bank_items WHERE id = ? AND guild_id = ?",
            (int(item_id), int(guild_id)),
        )

    async def guild_bank_get_transactions(self, guild_id: int, limit: int = 25):
        limit = max(1, min(int(limit), 100))
        return await self.fetchall(
            """
            SELECT * FROM guild_bank_transactions
            WHERE guild_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (int(guild_id), limit),
        )

    async def guild_bank_get_item_transactions(self, guild_id: int, item_id: int, limit: int = 25):
        limit = max(1, min(int(limit), 100))
        return await self.fetchall(
            """
            SELECT * FROM guild_bank_transactions
            WHERE guild_id = ? AND item_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (int(guild_id), int(item_id), limit),
        )
