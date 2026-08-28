CREATE TABLE IF NOT EXISTS corporate_action_events (
    instrument_id bigint NOT NULL REFERENCES instruments(id) ON DELETE CASCADE,
    event_date date NOT NULL,
    previous_factor numeric(18,10),
    new_factor numeric(18,10),
    ratio_change_pct numeric(18,8),
    source varchar(32) NOT NULL DEFAULT 'ssi',
    reconciliation_updated integer NOT NULL DEFAULT 0,
    reconciliation_inserted integer NOT NULL DEFAULT 0,
    processed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, event_date),
    CONSTRAINT corporate_action_events_counts_check CHECK (
        reconciliation_updated >= 0 AND reconciliation_inserted >= 0
    )
);

CREATE INDEX IF NOT EXISTS idx_corporate_action_events_event_date_desc
    ON corporate_action_events (event_date DESC);
