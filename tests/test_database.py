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
        if db.pool:
            await db.pool.close()


@pytest.mark.asyncio
async def test_clear_all_raid_member_groups_returns_deleted_count():
    db = Database(":memory:")
    try:
        await db.connect()

        raid_id = await db.execute_insert(
            "INSERT INTO raids (guild_id, leader_id, vc_id, thread_id, is_active) VALUES (?, ?, ?, ?, ?)",
            (1, 10, 200, 3000, 1),
        )

        await db.set_raid_member_group(raid_id, 111, 1)
        await db.set_raid_member_group(raid_id, 222, 2)

        deleted = await db.clear_all_raid_member_groups(raid_id)
        assert deleted == 2

        remaining = await db.get_raid_member_groups(raid_id)
        assert remaining == []
    finally:
        if db.pool:
            await db.pool.close()

@pytest.mark.asyncio
async def test_get_raid_by_thread():
    db = Database(":memory:")
    try:
        await db.connect()
        guild_id = 1
        leader_id = 10
        vc_id = 100
        thread_id_active = 1000
        thread_id_inactive = 1001
        thread_id_nonexistent = 1002

        # Insert an active raid
        await db.execute(
            "INSERT INTO raids (guild_id, leader_id, vc_id, thread_id, is_active) VALUES (?, ?, ?, ?, ?)",
            (guild_id, leader_id, vc_id, thread_id_active, 1)
        )
        # Insert an inactive raid
        await db.execute(
            "INSERT INTO raids (guild_id, leader_id, vc_id, thread_id, is_active) VALUES (?, ?, ?, ?, ?)",
            (guild_id, leader_id, vc_id + 1, thread_id_inactive, 0) # vc_id + 1 to avoid UNIQUE constraint if any on vc_id for active raids
        )

        # Test 1: Raid exists for the given thread ID and is active
        raid = await db.get_raid_by_thread(thread_id_active)
        assert raid is not None
        assert raid['thread_id'] == thread_id_active
        assert raid['is_active'] == 1

        # Test 2: No raid exists for the given thread ID (non-existent)
        raid = await db.get_raid_by_thread(thread_id_nonexistent)
        assert raid is None

        # Test 3: A raid exists for the given thread ID but is_active = 0
        raid = await db.get_raid_by_thread(thread_id_inactive)
        assert raid is None # Should not return inactive raids

    finally:
        if db.pool:
            await db.pool.close()

@pytest.mark.asyncio
async def test_get_raid_by_vc():
    db = Database(":memory:")
    try:
        await db.connect()
        guild_id = 1
        leader_id = 10
        vc_id_active = 200
        vc_id_inactive = 201
        vc_id_nonexistent = 202
        thread_id_base = 2000 # Base for unique thread IDs

        # Insert an active raid
        await db.execute(
            "INSERT INTO raids (guild_id, leader_id, vc_id, thread_id, is_active) VALUES (?, ?, ?, ?, ?)",
            (guild_id, leader_id, vc_id_active, thread_id_base, 1)
        )
        # Insert an inactive raid
        await db.execute(
            "INSERT INTO raids (guild_id, leader_id, vc_id, thread_id, is_active) VALUES (?, ?, ?, ?, ?)",
            (guild_id, leader_id, vc_id_inactive, thread_id_base + 1, 0)
        )

        # Test 1: Raid exists for the given VC ID and is active
        raid = await db.get_raid_by_vc(vc_id_active)
        assert raid is not None
        assert raid['vc_id'] == vc_id_active
        assert raid['is_active'] == 1

        # Test 2: No raid exists for the given VC ID (non-existent)
        raid = await db.get_raid_by_vc(vc_id_nonexistent)
        assert raid is None

        # Test 3: A raid exists for the given VC ID but is_active = 0
        raid = await db.get_raid_by_vc(vc_id_inactive)
        assert raid is None # Should not return inactive raids

    finally:
        if db.pool:
            await db.pool.close()

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
        if db.pool:
            await db.pool.close()

@pytest.mark.asyncio
async def test_get_active_auction():
    db = Database(":memory:")
    try:
        await db.connect()
        guild_id = 1
        leader_id = 10
        vc_id = 300
        thread_id_raid1 = 3000
        # Insert a raid to link auctions to
        raid_id_1 = await db.execute_insert(
            "INSERT INTO raids (guild_id, leader_id, vc_id, thread_id, is_active) VALUES (?, ?, ?, ?, ?)",
            (guild_id, leader_id, vc_id, thread_id_raid1, 1)
        )

        # Insert another raid for testing no active auction
        raid_id_2 = await db.execute_insert(
            "INSERT INTO raids (guild_id, leader_id, vc_id, thread_id, is_active) VALUES (?, ?, ?, ?, ?)",
            (guild_id, leader_id, vc_id + 1, thread_id_raid1 + 1, 1)
        )

        item_name_active = "Active Item"
        item_name_inactive = "Inactive Item"

        # Insert an active auction for raid_id_1
        await db.execute(
            "INSERT INTO auctions (raid_id, item_name, is_active, highest_bidder_id, highest_bid, message_id) VALUES (?, ?, ?, ?, ?, ?)",
            (raid_id_1, item_name_active, 1, None, 0, 12345)
        )
        # Insert an inactive auction for raid_id_1
        await db.execute(
            "INSERT INTO auctions (raid_id, item_name, is_active, highest_bidder_id, highest_bid, message_id) VALUES (?, ?, ?, ?, ?, ?)",
            (raid_id_1, item_name_inactive, 0, None, 0, 12346)
        )

        # Test 1: An active auction exists for the given raid_id
        auction = await db.get_active_auction(raid_id_1)
        assert auction is not None
        assert auction['raid_id'] == raid_id_1
        assert auction['item_name'] == item_name_active
        assert auction['is_active'] == 1

        # Test 2: No active auction exists for a different raid_id (raid_id_2 has no auctions)
        auction = await db.get_active_auction(raid_id_2)
        assert auction is None

        # Test 3: (Covered by Test 1 logic) Multiple auctions exist for raid_id_1, but only one is active.
        # The function should return the active one.

        # Test 4: If we make the active auction inactive, it should not be found.
        await db.execute("UPDATE auctions SET is_active = 0 WHERE item_name = ?", (item_name_active,))
        auction = await db.get_active_auction(raid_id_1)
        assert auction is None


    finally:
        if db.pool:
            await db.pool.close()

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
        if db.pool:
            await db.pool.close()
