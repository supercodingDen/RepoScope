CREATE TABLE reposcope.repositories (
    repository_id uuid PRIMARY KEY,
    principal_id uuid NOT NULL,
    url text NOT NULL,
    active_generation_id uuid,
    latest_requested_generation_id uuid,
    created_at timestamptz NOT NULL,
    UNIQUE (principal_id, url),
    UNIQUE (repository_id, principal_id)
);
CREATE TABLE reposcope.source_revisions (
    repository_id uuid NOT NULL,
    principal_id uuid NOT NULL,
    commit_sha text NOT NULL CHECK (commit_sha ~ '^[a-f0-9]{40}$'),
    created_at timestamptz NOT NULL,
    PRIMARY KEY (repository_id, commit_sha),
    FOREIGN KEY (repository_id, principal_id)
        REFERENCES reposcope.repositories (repository_id, principal_id)
);
CREATE TABLE reposcope.index_generations (
    generation_id uuid PRIMARY KEY,
    repository_id uuid NOT NULL,
    principal_id uuid NOT NULL,
    requested_ref text NOT NULL,
    commit_sha text,
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'staged', 'ready', 'failed', 'superseded')),
    parser_version text,
    tokenizer_version text,
    embedding_space_version text,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL CHECK (updated_at >= created_at),
    CHECK (status <> 'ready' OR commit_sha IS NOT NULL),
    FOREIGN KEY (repository_id, principal_id)
        REFERENCES reposcope.repositories (repository_id, principal_id),
    FOREIGN KEY (repository_id, commit_sha)
        REFERENCES reposcope.source_revisions (repository_id, commit_sha),
    UNIQUE (generation_id, repository_id, principal_id),
    UNIQUE (generation_id, repository_id, principal_id, commit_sha)
);
ALTER TABLE reposcope.repositories ADD FOREIGN KEY
    (active_generation_id, repository_id, principal_id)
    REFERENCES reposcope.index_generations (generation_id, repository_id, principal_id);
ALTER TABLE reposcope.repositories ADD FOREIGN KEY
    (latest_requested_generation_id, repository_id, principal_id)
    REFERENCES reposcope.index_generations (generation_id, repository_id, principal_id);
CREATE TABLE reposcope.jobs (
    job_id uuid PRIMARY KEY,
    repository_id uuid NOT NULL,
    generation_id uuid NOT NULL UNIQUE,
    principal_id uuid NOT NULL,
    requested_ref text NOT NULL,
    commit_sha text,
    status text NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 5),
    progress_percent integer NOT NULL DEFAULT 0 CHECK (progress_percent BETWEEN 0 AND 100),
    failure_code varchar(80),
    lease_owner uuid,
    lease_until timestamptz,
    fencing_token bigint NOT NULL DEFAULT 0 CHECK (fencing_token >= 0),
    deadline_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL CHECK (updated_at >= created_at),
    CHECK ((status = 'failed') = (failure_code IS NOT NULL)),
    CHECK (status <> 'succeeded' OR (progress_percent = 100 AND commit_sha IS NOT NULL)),
    FOREIGN KEY (generation_id, repository_id, principal_id)
        REFERENCES reposcope.index_generations (generation_id, repository_id, principal_id),
    FOREIGN KEY (generation_id, repository_id, principal_id, commit_sha)
        REFERENCES reposcope.index_generations
            (generation_id, repository_id, principal_id, commit_sha),
    FOREIGN KEY (repository_id, commit_sha)
        REFERENCES reposcope.source_revisions (repository_id, commit_sha),
    UNIQUE (job_id, principal_id)
);
CREATE TABLE reposcope.agent_runs (
    run_id uuid PRIMARY KEY,
    repository_id uuid NOT NULL,
    generation_id uuid NOT NULL,
    principal_id uuid NOT NULL,
    commit_sha text NOT NULL,
    question text NOT NULL CHECK (length(question) BETWEEN 1 AND 4000),
    policy_version text NOT NULL DEFAULT 'routing-v1' CHECK (policy_version = 'routing-v1'),
    status text NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
    result jsonb,
    failure_code varchar(80),
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 6),
    tool_steps integer NOT NULL DEFAULT 0 CHECK (tool_steps BETWEEN 0 AND 6),
    lease_owner uuid,
    lease_until timestamptz,
    fencing_token bigint NOT NULL DEFAULT 0 CHECK (fencing_token >= 0),
    deadline_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL CHECK (updated_at >= created_at),
    CHECK ((status = 'succeeded') = (result IS NOT NULL)),
    CHECK (result IS NULL OR jsonb_typeof(result) = 'object'),
    CHECK ((status = 'failed') = (failure_code IS NOT NULL)),
    FOREIGN KEY (generation_id, repository_id, principal_id, commit_sha)
        REFERENCES reposcope.index_generations
            (generation_id, repository_id, principal_id, commit_sha),
    UNIQUE (run_id, principal_id)
);
CREATE TABLE reposcope.outbox_events (
    event_id uuid PRIMARY KEY,
    principal_id uuid NOT NULL,
    aggregate_id uuid NOT NULL,
    event_type text NOT NULL CHECK (event_type IN ('repo.ingest.requested', 'agent.run.requested')),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    occurred_at timestamptz NOT NULL,
    trace_id uuid NOT NULL,
    published_at timestamptz,
    lease_owner uuid,
    lease_until timestamptz,
    fencing_token bigint NOT NULL DEFAULT 0 CHECK (fencing_token >= 0),
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    next_attempt_at timestamptz,
    job_id uuid,
    run_id uuid,
    CHECK ((event_type = 'repo.ingest.requested' AND job_id = aggregate_id AND run_id IS NULL)
        OR (event_type = 'agent.run.requested' AND run_id = aggregate_id AND job_id IS NULL)),
    CHECK (num_nonnulls(job_id, run_id) = 1),
    FOREIGN KEY (job_id, principal_id) REFERENCES reposcope.jobs (job_id, principal_id),
    FOREIGN KEY (run_id, principal_id) REFERENCES reposcope.agent_runs (run_id, principal_id),
    UNIQUE (event_type, aggregate_id)
);
CREATE TABLE reposcope.idempotency_requests (
    principal_id uuid NOT NULL,
    route text NOT NULL CHECK (route IN ('/v1/repositories', '/v1/runs')),
    idempotency_key varchar(128) NOT NULL CHECK (idempotency_key ~ '^[!-~]{1,128}$'),
    fingerprint text NOT NULL CHECK (fingerprint ~ '^[a-f0-9]{64}$'),
    response jsonb NOT NULL CHECK (jsonb_typeof(response) = 'object'),
    response_status integer NOT NULL DEFAULT 202 CHECK (response_status = 202),
    job_id uuid,
    run_id uuid,
    created_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL CHECK (expires_at >= created_at + interval '7 days'),
    PRIMARY KEY (principal_id, route, idempotency_key),
    CHECK ((route = '/v1/repositories' AND job_id IS NOT NULL AND run_id IS NULL)
        OR (route = '/v1/runs' AND run_id IS NOT NULL AND job_id IS NULL)),
    FOREIGN KEY (job_id, principal_id) REFERENCES reposcope.jobs (job_id, principal_id),
    FOREIGN KEY (run_id, principal_id) REFERENCES reposcope.agent_runs (run_id, principal_id)
);
CREATE TABLE reposcope.consumer_work (
    consumer text NOT NULL,
    event_id uuid NOT NULL REFERENCES reposcope.outbox_events (event_id),
    lease_owner uuid,
    lease_until timestamptz,
    fencing_token bigint NOT NULL DEFAULT 0 CHECK (fencing_token >= 0),
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    deadline_at timestamptz NOT NULL,
    completed_at timestamptz,
    PRIMARY KEY (consumer, event_id)
);
CREATE TABLE reposcope.usage_reservations (
    reservation_id uuid PRIMARY KEY,
    run_id uuid NOT NULL UNIQUE,
    principal_id uuid NOT NULL,
    amount_usd numeric(18,6) NOT NULL CHECK (amount_usd >= 0 AND amount_usd <> 'NaN'),
    state text NOT NULL CHECK (state IN ('reserved', 'settled', 'uncertain', 'released')),
    budget_day date NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL CHECK (updated_at >= created_at),
    FOREIGN KEY (run_id, principal_id) REFERENCES reposcope.agent_runs (run_id, principal_id)
);
CREATE TABLE reposcope.admission_lock (singleton boolean PRIMARY KEY CHECK (singleton));
INSERT INTO reposcope.admission_lock VALUES (true);
CREATE INDEX jobs_pending ON reposcope.jobs (status) WHERE status IN ('queued', 'running');
CREATE INDEX runs_pending ON reposcope.agent_runs (status) WHERE status IN ('queued', 'running');
CREATE INDEX reservations_accounting ON reposcope.usage_reservations (budget_day, state);
CREATE INDEX outbox_unpublished ON reposcope.outbox_events (occurred_at)
    WHERE published_at IS NULL;
