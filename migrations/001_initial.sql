CREATE TABLE IF NOT EXISTS instruments (
    id bigserial PRIMARY KEY,
    symbol varchar(20) NOT NULL,
    exchange varchar(20) NOT NULL,
    name varchar(255) NOT NULL,
    provider varchar(32) NOT NULL DEFAULT 'vnstock',
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT instruments_symbol_exchange_key UNIQUE (symbol, exchange)
);

CREATE TABLE IF NOT EXISTS daily_candles (
    id bigserial PRIMARY KEY,
    instrument_id bigint NOT NULL REFERENCES instruments(id) ON DELETE CASCADE,
    trade_date date NOT NULL,
    open numeric(18,6) NOT NULL,
    high numeric(18,6) NOT NULL,
    low numeric(18,6) NOT NULL,
    close numeric(18,6) NOT NULL,
    volume numeric(24,2) NOT NULL DEFAULT 0,
    provider varchar(32) NOT NULL DEFAULT 'vnstock',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT daily_candles_instrument_date_key UNIQUE (instrument_id, trade_date),
    CONSTRAINT daily_candles_ohlc_check CHECK (
        high >= low
        AND high >= open
        AND high >= close
        AND low <= open
        AND low <= close
        AND open >= 0
        AND close >= 0
        AND volume >= 0
    )
);

CREATE INDEX IF NOT EXISTS idx_daily_candles_instrument_date_desc
    ON daily_candles (instrument_id, trade_date DESC);

CREATE TABLE IF NOT EXISTS sync_status (
    instrument_id bigint PRIMARY KEY REFERENCES instruments(id) ON DELETE CASCADE,
    last_sync_date date,
    status varchar(20) NOT NULL DEFAULT 'never',
    error_count integer NOT NULL DEFAULT 0,
    last_error text,
    last_attempt_at timestamptz,
    last_success_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT sync_status_error_count_check CHECK (error_count >= 0)
);

INSERT INTO instruments(symbol, exchange, name, provider, active)
VALUES
    ('FPT', 'HOSE', 'FPT', 'vnstock', true),
    ('HPG', 'HOSE', 'Hoa Phat Group', 'vnstock', true),
    ('MBB', 'HOSE', 'MB Bank', 'vnstock', true),
    ('DGC', 'HOSE', 'Duc Giang Chemicals', 'vnstock', true),
    ('VIX', 'HOSE', 'VIX Securities', 'vnstock', true)
ON CONFLICT (symbol, exchange) DO UPDATE
SET name = EXCLUDED.name,
    provider = EXCLUDED.provider,
    active = EXCLUDED.active,
    updated_at = now();

INSERT INTO sync_status(instrument_id)
SELECT id FROM instruments
WHERE symbol IN ('FPT', 'HPG', 'MBB', 'DGC', 'VIX')
ON CONFLICT (instrument_id) DO NOTHING;
