import pytest
from discord_bot.database import Database

@pytest.mark.asyncio
async def test_create_tables():
    """Test that all tables are created on connection."""
    db = Database(":memory:")
    try:
        await db.connect()
        tables = ['guilds', 'users', 'raids', 'auctions', 'transactions']
        for table in tables:
            row = await db.fetchone(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'")
            assert row is not None, f"Table '{table}' was not created."
    finally:
        if db.conn:
            await db.conn.close()

@pytest.mark.asyncio
async def test_add_and_get_guild_config():
    """Test adding and then getting a guild config."""
    db = Database(":memory:")
    try:
        await db.connect()
        guild_id = 12345
        await db.execute(
            "INSERT INTO guilds (guild_id, dkp_category_id, dkp_channel_id, raid_channel_id, officer_role_id) VALUES (?, ?, ?, ?, ?)",
            (guild_id, 1, 2, 3, 4)
        )
        
        config = await db.get_guild_config(guild_id)
        assert config is not None
        assert config['guild_id'] == guild_id
        assert config['dkp_category_id'] == 1
        assert config['officer_role_id'] == 4
    finally:
        if db.conn:
            await db.conn.close()

@pytest.mark.asyncio
async def test_get_and_modify_dkp():
    """Test DKP operations for a user."""
    db = Database(":memory:")
    try:
        await db.connect()
        guild_id = 12345
        user_id = 54321
        
        # First time getting DKP should create user and return 0
        dkp = await db.get_user_dkp(user_id, guild_id)
        assert dkp == 0
        
        # Check if user was added to the table
        user_row = await db.fetchone("SELECT * FROM users WHERE user_id = ? AND guild_id = ?", (user_id, guild_id))
        assert user_row is not None
        assert user_row['dkp'] == 0
        
        # Modify DKP
        await db.modify_user_dkp(user_id, guild_id, 10, "Test award")
        dkp = await db.get_user_dkp(user_id, guild_id)
        assert dkp == 10
        
        # Check transaction log
        transaction = await db.fetchone("SELECT * FROM transactions WHERE user_id = ? AND guild_id = ?", (user_id, guild_id))
        assert transaction is not None
        assert transaction['change'] == 10
        assert transaction['reason'] == "Test award"
        
        # Modify DKP again
        await db.modify_user_dkp(user_id, guild_id, -5, "Test purchase")
        dkp = await db.get_user_dkp(user_id, guild_id)
        assert dkp == 5
    finally:
        if db.conn:
            await db.conn.close()
