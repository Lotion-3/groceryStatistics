-- groceryStatistics schema (spec section 5).
-- Portable SQL: runs unchanged on SQLite (default, data/grocery.sqlite) and on
-- Postgres. These are NEW tables in a NEW database; nothing here touches the
-- basketBuddy production Supabase project or its `prices` table.
--
-- Additions beyond the spec are marked "-- (added)" and justified in
-- docs/DECISIONS.md.

CREATE TABLE IF NOT EXISTS stores (
    store_pk      INTEGER PRIMARY KEY,
    chain         TEXT    NOT NULL,             -- walmart | target | costco | trader_joes
    store_id      TEXT    NOT NULL,             -- the chain's own store id (Instacart shop id for costco)
    name          TEXT,
    lat           REAL,
    lon           REAL,
    zip           TEXT,
    state         TEXT,
    region        TEXT,                         -- Census region: Northeast | Midwest | South | West
    urbanicity    TEXT,                         -- urban | suburban | rural (from RUCA, see SAMPLING.md)
    source        TEXT    NOT NULL,             -- direct | instacart | national
    ruca          INTEGER,                      -- (added) primary RUCA code of the ZIP
    anchor_zip    TEXT,                         -- (added) sampled ZIP this store was anchored to (walmart/costco)
    coord_quality TEXT,                         -- (added) slug_geocode | zip_centroid | anchor_zip (see SAMPLING.md)
    address       TEXT,                         -- (added) street address as reported by the retailer
    UNIQUE (chain, store_id, source)
);

CREATE TABLE IF NOT EXISTS items (
    item_id       TEXT    PRIMARY KEY,
    name          TEXT    NOT NULL,
    upc           TEXT,                         -- 12-digit UPC-A, filled ONLY from retailer data
    category      TEXT    NOT NULL,
    cross_chain   INTEGER NOT NULL DEFAULT 0,   -- boolean (0/1)
    size_value    REAL,
    size_unit     TEXT,
    search_term   TEXT,                         -- (added) query sent to retailer search
    walmart_id    TEXT,                         -- (added) Walmart usItemId once resolved
    target_tcin   TEXT,                         -- (added) Target TCIN once resolved
    costco_ic_id  TEXT,                         -- (added) Instacart item id prefix for Costco
    tj_sku        TEXT                          -- (added) Trader Joe's SKU once resolved
);

CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id   INTEGER PRIMARY KEY,
    started_at    TEXT    NOT NULL,             -- ISO 8601 UTC
    ended_at      TEXT,
    notes         TEXT
);

CREATE TABLE IF NOT EXISTS observations (
    obs_id            INTEGER PRIMARY KEY,
    snapshot_id       INTEGER NOT NULL REFERENCES snapshots(snapshot_id),
    store_pk          INTEGER NOT NULL REFERENCES stores(store_pk),
    item_id           TEXT    NOT NULL REFERENCES items(item_id),
    observed_at       TEXT    NOT NULL,
    product_name      TEXT,
    brand             TEXT,
    upc               TEXT,
    price             REAL,                     -- price shown now (sale price if on sale)
    regular_price     REAL,                     -- list/"was" price when the retailer reports one
    promo_price       REAL,                     -- current price when it is below regular_price
    is_promo          INTEGER,                  -- 1 iff regular_price > price (computed, never overwrites raw)
    unit_price        REAL,
    unit_price_unit   TEXT,
    pack_size         TEXT,
    in_stock          INTEGER,                  -- NULL when the retailer does not say
    currency          TEXT    DEFAULT 'USD',
    store_specific    INTEGER NOT NULL,         -- 0 when the price is not tied to this store (fallback / national)
    raw_path          TEXT    NOT NULL,         -- gzipped raw response this row was parsed from
    chain_product_id  TEXT    NOT NULL,         -- (added) usItemId / tcin / Instacart item id / TJ sku
    search_rank       INTEGER,                  -- (added) 0-based position in the result list
    priced_store_id   TEXT,                     -- (added) store the retailer says it priced at
    source            TEXT    NOT NULL,         -- (added) direct | instacart | national
    extra             TEXT,                     -- (added) JSON: chain-specific fields (seller, price type, promo text, ...)
    UNIQUE (snapshot_id, store_pk, item_id, chain_product_id)
);

CREATE TABLE IF NOT EXISTS collection_failures (
    fail_id       INTEGER PRIMARY KEY,
    snapshot_id   INTEGER REFERENCES snapshots(snapshot_id),
    chain         TEXT    NOT NULL,
    store_pk      INTEGER,
    item_id       TEXT,
    occurred_at   TEXT    NOT NULL,
    reason        TEXT    NOT NULL,             -- category:detail, e.g. "explicit:px-captcha marker"
    raw_path      TEXT                          -- (added) response body when one was received
);

CREATE INDEX IF NOT EXISTS idx_obs_item_store ON observations (item_id, store_pk);
CREATE INDEX IF NOT EXISTS idx_obs_snapshot   ON observations (snapshot_id);
CREATE INDEX IF NOT EXISTS idx_fail_snapshot  ON collection_failures (snapshot_id, chain);
