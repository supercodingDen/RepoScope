ALTER TABLE reposcope.outbox_events DROP CONSTRAINT outbox_events_event_type_check;
ALTER TABLE reposcope.outbox_events ADD CONSTRAINT outbox_events_event_type_check
    CHECK (event_type IN ('repo.ingest.requested', 'agent.run.requested', 'repo.source.acquired'));
ALTER TABLE reposcope.outbox_events DROP CONSTRAINT outbox_events_check;
ALTER TABLE reposcope.outbox_events ADD CONSTRAINT outbox_events_check
    CHECK ((event_type IN ('repo.ingest.requested', 'repo.source.acquired')
        AND job_id = aggregate_id AND run_id IS NULL)
        OR (event_type = 'agent.run.requested' AND run_id = aggregate_id AND job_id IS NULL));
ALTER TABLE reposcope.jobs ADD CONSTRAINT jobs_source_scope UNIQUE(job_id,generation_id,repository_id,principal_id,commit_sha);
CREATE TABLE reposcope.source_attempts (
    job_id uuid NOT NULL REFERENCES reposcope.jobs(job_id),
    fencing_token bigint NOT NULL CHECK (fencing_token > 0),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    cleaned_at timestamptz,
    PRIMARY KEY(job_id, fencing_token)
);
CREATE TABLE reposcope.source_manifests (
    job_id uuid PRIMARY KEY REFERENCES reposcope.jobs(job_id),
    repository_id uuid NOT NULL,
    generation_id uuid NOT NULL UNIQUE,
    principal_id uuid NOT NULL,
    commit_sha text NOT NULL,
    manifest_digest text NOT NULL CHECK (manifest_digest ~ '^[a-f0-9]{64}$'),
    manifest jsonb NOT NULL CHECK (jsonb_typeof(manifest) = 'object'),
    storage_key text NOT NULL CHECK (storage_key ~ '^snapshots/[a-f0-9-]{36}-[1-9][0-9]*/[a-f0-9]{64}$'),
    policy_version text NOT NULL CHECK (policy_version = 'source-v1'),
    fencing_token bigint NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY(job_id,generation_id,repository_id,principal_id,commit_sha)
        REFERENCES reposcope.jobs(job_id,generation_id,repository_id,principal_id,commit_sha),
    FOREIGN KEY(job_id, fencing_token) REFERENCES reposcope.source_attempts(job_id, fencing_token),
    FOREIGN KEY(generation_id, repository_id, principal_id, commit_sha)
        REFERENCES reposcope.index_generations(generation_id, repository_id, principal_id, commit_sha)
);
