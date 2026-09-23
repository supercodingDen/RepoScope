ALTER TABLE reposcope.jobs ADD COLUMN next_attempt_at timestamptz;
ALTER TABLE reposcope.agent_runs ADD COLUMN next_attempt_at timestamptz;
ALTER TABLE reposcope.agent_runs ADD COLUMN delivery_attempts integer NOT NULL DEFAULT 0
    CHECK (delivery_attempts BETWEEN 0 AND 5);
ALTER TABLE reposcope.consumer_work ADD COLUMN next_attempt_at timestamptz;
CREATE TABLE reposcope.delivery_completions (
    consumer text NOT NULL,
    event_id uuid NOT NULL,
    aggregate_id uuid NOT NULL,
    outcome text NOT NULL CHECK (outcome IN ('succeeded','failed','staged')),
    failure_code varchar(80) CHECK (failure_code ~ '^[A-Z][A-Z0-9_]{0,79}$'),
    completed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (consumer,event_id),
    FOREIGN KEY (consumer,event_id) REFERENCES reposcope.consumer_work (consumer,event_id),
    CHECK ((outcome='failed') = (failure_code IS NOT NULL))
);
CREATE TABLE reposcope.delivery_quarantine (
    fingerprint char(64) PRIMARY KEY CHECK (fingerprint ~ '^[a-f0-9]{64}$'),
    reason varchar(32) NOT NULL CHECK (reason IN ('INVALID_EVENT','UNAUTHORIZED_EVENT')),
    consumer varchar(16) NOT NULL CHECK (consumer IN ('indexer','agent')),
    byte_count integer NOT NULL CHECK (byte_count BETWEEN 0 AND 65536),
    occurrences bigint NOT NULL DEFAULT 1 CHECK (occurrences BETWEEN 1 AND 2147483647),
    first_seen_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    last_seen_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX consumer_work_recovery ON reposcope.consumer_work (lease_until)
    WHERE completed_at IS NULL;
