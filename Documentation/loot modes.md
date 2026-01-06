# Loot Modes Specification

## 1. Make loot resolution pluggable

Introduce a concept like `LootMode`.

- **Core idea**
  - For each dropped item, the bot calls a loot mode handler that:
    - Gets: raid context, item info, list of eligible players, current balances/reserves/etc.
    - Drives: the Discord UI flow (buttons/selects, prompts, rolls, etc.).
    - Returns: a final assignment record: who got it, why, and any point/metadata changes.

- **Data model additions (generic)**
  - `loot_items`:
    - `id`
    - `raid_id`
    - `item_name`
    - `item_id`
    - `slot`
    - `mode_used`
    - `winner_id`
    - `resolution_log_json`
  - `loot_candidates`:
    - Optional per-item list of eligible players (esp. for council).
  - `loot_mode_config`:
    - Per‑guild (and optional per‑raid) config:
      - Default mode (e.g. `DKP_AUCTION`, `LOOT_COUNCIL`, `SOFT_RESERVE`, …)
      - Mode-specific settings (e.g. max SR per player, council role ID).

- **Existing DKP auction**
  - Your existing DKP auction becomes one implementation of this interface.

---

## 2. Loot council mode

- **Extra config/data**
  - List of council members (role or explicit user IDs).
  - Optional visibility: public vs secret votes.

- **Flow**
  - Item is announced; loot mode = `LOOT_COUNCIL`.
  - Bot posts a council-only panel:
    - Eligible raiders (dropdown).
    - Buttons: “Vote for X”, “Abstain”, “Pass”, etc.
  - Council members click; bot records votes in `resolution_log_json`.
  - Once council is satisfied, someone presses “Finalize”:
    - Bot chooses winner (simple majority, highest votes, or a function you define).
    - Logs: winner, all votes, timestamps.
  - Optionally: no DKP change, but you still keep immutable raid log.

- **Why this fits the plugin model**
  - It doesn’t care how you track points; it just uses the same “item → resolution record” interface.

---

## 3. Soft reserve (SR) mode

- **Extra config/data**
  - Pre‑raid SR submissions (`soft_reserves`):
    - `player_id`
    - `item_id`
    - `priority`
    - `source_raid_id` (optional)
  - Limits per player (e.g. 1–3 SRs per lockout).

- **Pre‑raid**
  - Players use `/soft_reserve <item>` or submit via a form.
  - Bot validates limits, stores reserves.

- **On drop**
  - Item appears; mode = `SOFT_RESERVE`.
  - Handler looks up reserves:
    - 0 reservers → fallback to another mode (e.g. DKP auction, open roll).
    - 1 reserver → auto-assign (optionally confirm).
    - >1 reservers → either:
      - Random roll among reservers, or
      - Council / DKP tiebreaker (configurable).
  - Result stored as a resolution record with reason: `"Soft reserve winner"` etc.

---

## 4. SR + roll mode

Essentially `SOFT_RESERVE` with a built-in random roll step for contested items:

- **When multiple SRs**
  - Bot does `/roll` internally (e.g. 1–100 per reserver) and posts the results.
  - Highest roll wins; result logged.

- **Implementation options**
  - `SOFT_RESERVE` + setting `tiebreaker = ROLL`, or
  - Separate `SOFT_RESERVE_ROLL` mode class, same interface.

---

## 5. Wishlist mode

- **Extra data**
  - Per-player wishlist, maybe with priority:
    - `wishlist_entries`: `player_id`, `item_id`, `rank`.

- **Flow**
  - On drop, handler checks wishlists:
    - Players with the item on their list get priority.
    - Tie-break mechanisms: rank, number of previous wins, roll, or council.
  - Still outputs a single standardized resolution record.

- **Relation to SR**
  - This can share a lot of plumbing with SR (just using “wish rank” instead of “strict reserve”).
