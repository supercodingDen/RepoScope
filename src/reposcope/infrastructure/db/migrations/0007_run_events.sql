CREATE TABLE reposcope.run_events (
    run_id uuid NOT NULL REFERENCES reposcope.agent_runs(run_id),
    sequence bigint NOT NULL CHECK (sequence > 0),
    occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    data jsonb NOT NULL CHECK (jsonb_typeof(data) = 'object'),
    kind text GENERATED ALWAYS AS (data->>'kind') STORED,
    PRIMARY KEY (run_id, sequence),
    CHECK (kind IN ('run.started','tool.started','tool.completed',
        'run.completed','run.failed')),
    CHECK (octet_length(data::text) <= 65536)
);
CREATE UNIQUE INDEX run_events_one_terminal ON reposcope.run_events(run_id)
    WHERE kind IN ('run.completed','run.failed');
CREATE UNIQUE INDEX run_events_one_start ON reposcope.run_events(run_id)
    WHERE kind = 'run.started';

INSERT INTO reposcope.run_events(run_id,sequence,occurred_at,data)
SELECT run_id,1,updated_at,
    CASE WHEN status='succeeded' THEN
        jsonb_build_object('kind','run.completed','result',result)
    ELSE
        jsonb_build_object('kind','run.failed','code',failure_code,
            'message','The run could not be completed.')
    END
FROM reposcope.agent_runs WHERE status IN ('succeeded','failed');

CREATE TABLE reposcope.sse_connections (
    connection_id uuid PRIMARY KEY,
    principal_id uuid NOT NULL,
    run_id uuid NOT NULL REFERENCES reposcope.agent_runs(run_id),
    expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX sse_connections_expiry ON reposcope.sse_connections(expires_at);
