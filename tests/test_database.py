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
async def test_get_raid_by_thread_any_state_returns_inactive_raid():
    db = Database(":memory:")
    try:
        await db.connect()
        await db.execute(
            "INSERT INTO raids (guild_id, leader_id, vc_id, thread_id, is_active) VALUES (?, ?, ?, ?, ?)",
            (1, 10, 101, 1001, 0),
        )

        raid = await db.get_raid_by_thread_any_state(1001)

        assert raid is not None
        assert raid["thread_id"] == 1001
        assert raid["is_active"] == 0
    finally:
        if db.pool:
            await db.pool.close()


@pytest.mark.asyncio
async def test_get_raid_dkp_transactions_from_cutoff_filters_scope_and_skips_referenced_rows():
    db = Database(":memory:")
    try:
        await db.connect()
        await db.execute(
            "INSERT INTO raids (guild_id, leader_id, vc_id, thread_id, is_active) VALUES (?, ?, ?, ?, ?)",
            (1, 10, 100, 2000, 0),
        )
        raid = await db.get_raid_by_thread_any_state(2000)
        raid_id = int(raid["id"])

        await db.execute(
            "INSERT INTO raid_dkp_transactions (raid_id, guild_id, user_id, change, reason, actor_id, reference_transaction_id, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (raid_id, 1, 111, 5, "Award: Boss kill", 10, None, "2026-04-12 18:00:00"),
        )
        await db.execute(
            "INSERT INTO raid_dkp_transactions (raid_id, guild_id, user_id, change, reason, actor_id, reference_transaction_id, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (raid_id, 1, 111, 3, "Timed raid award (+3 every 6m)", None, None, "2026-04-12 19:00:00"),
        )
        await db.execute(
            "INSERT INTO raid_dkp_transactions (raid_id, guild_id, user_id, change, reason, actor_id, reference_transaction_id, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (raid_id, 1, 222, -2, "Deduct: Death", 10, None, "2026-04-12 19:30:00"),
        )
        await db.execute(
            "INSERT INTO raid_dkp_transactions (raid_id, guild_id, user_id, change, reason, actor_id, reference_transaction_id, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (raid_id, 1, 111, -3, "Reverse Raid DKP From Cutoff: cleanup", 10, 2, "2026-04-12 19:35:00"),
        )
        await db.execute(
            "INSERT INTO raid_dkp_transactions (raid_id, guild_id, user_id, change, reason, actor_id, reference_transaction_id, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (raid_id, 1, 333, 4, "Award: Late boss", 10, None, "2026-04-12 20:00:00"),
        )

        all_rows = await db.get_raid_dkp_transactions_from_cutoff(
            raid_id,
            "2026-04-12 18:30:00",
            timed_only=False,
        )
        timed_rows = await db.get_raid_dkp_transactions_from_cutoff(
            raid_id,
            "2026-04-12 18:30:00",
            timed_only=True,
        )

        assert [int(row["id"]) for row in all_rows] == [5]
        assert timed_rows == []
    finally:
        if db.pool:
            await db.pool.close()


@pytest.mark.asyncio
async def test_apply_raid_dkp_reversal_for_user_rolls_back_on_reference_insert_failure():
    db = Database(":memory:")
    try:
        await db.connect()
        await db.execute(
            "INSERT INTO users (user_id, guild_id, dkp) VALUES (?, ?, ?)",
            (111, 1, 25),
        )

        await db.execute(
            "INSERT INTO raids (guild_id, leader_id, vc_id, thread_id, is_active) VALUES (?, ?, ?, ?, ?)",
            (1, 10, 100, 2001, 0),
        )
        raid = await db.get_raid_by_thread_any_state(2001)
        raid_id = int(raid["id"])

        await db.execute(
            "INSERT INTO raid_dkp_transactions (raid_id, guild_id, user_id, change, reason, actor_id, reference_transaction_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (raid_id, 1, 111, 5, "Award: Boss kill", 10, None),
        )

        with pytest.raises(Exception):
            await db.apply_raid_dkp_reversal_for_user(
                raid_id=raid_id,
                guild_id=1,
                user_id=111,
                total_delta=-5,
                reversal_reason="Reverse Raid DKP From Cutoff: cleanup",
                source_rows=[("bad-source-id", 5)],
                actor_id=10,
                username="RaiderOne",
            )

        user = await db.fetchone("SELECT dkp, username FROM users WHERE user_id = ? AND guild_id = ?", (111, 1))
        tx_rows = await db.fetchall(
            "SELECT change, reason FROM transactions WHERE guild_id = ? AND user_id = ? ORDER BY id ASC",
            (1, 111),
        )
        raid_rows = await db.fetchall(
            "SELECT change, reference_transaction_id FROM raid_dkp_transactions WHERE raid_id = ? ORDER BY id ASC",
            (raid_id,),
        )

        assert int(user["dkp"]) == 25
        assert user["username"] is None
        assert tx_rows == []
        assert len(raid_rows) == 1
        assert int(raid_rows[0]["change"]) == 5
        assert raid_rows[0]["reference_transaction_id"] is None
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


@pytest.mark.asyncio
async def test_guild_bank_deposit_reuses_gap_ids():
    """Depleted item slots (deleted rows) should be reused by the next deposit."""
    db = Database(":memory:")
    try:
        await db.connect()
        guild_id = 999
        actor_id = 1

        async def deposit(name, qty=1):
            return await db.guild_bank_deposit(
                guild_id=guild_id,
                item_name=name,
                quantity=qty,
                category="other",
                location="vault",
                held_by_user_id=actor_id,
                actor_id=actor_id,
            )

        # Deposit 4 items → IDs 1, 2, 3, 4
        id1 = await deposit("Item A")
        id2 = await deposit("Item B")
        id3 = await deposit("Item C")
        id4 = await deposit("Item D")
        assert [id1, id2, id3, id4] == [1, 2, 3, 4]

        # Fully withdraw item 2 → row deleted, gap at ID 2
        await db.guild_bank_withdraw(guild_id, id2, 1, actor_id=actor_id)
        row = await db.fetchone("SELECT id FROM guild_bank_items WHERE id = ?", (id2,))
        assert row is None, "Item B row should have been deleted after full withdrawal"

        # Next deposit must fill the gap: should get ID 2 again
        id5 = await deposit("Item E")
        assert id5 == 2, f"Expected gap ID 2 to be reused, got {id5}"

        # Withdraw items 1 and 3 → gaps at 1 and 3
        await db.guild_bank_withdraw(guild_id, id1, 1, actor_id=actor_id)
        await db.guild_bank_withdraw(guild_id, id3, 1, actor_id=actor_id)

        # Next two deposits should fill gap 1 then gap 3
        id6 = await deposit("Item F")
        id7 = await deposit("Item G")
        assert id6 == 1, f"Expected gap ID 1 to be reused, got {id6}"
        assert id7 == 3, f"Expected gap ID 3 to be reused, got {id7}"

    finally:
        if db.pool:
            await db.pool.close()
