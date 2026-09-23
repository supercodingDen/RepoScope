CREATE TABLE reposcope.model_attempts (
    run_id uuid NOT NULL REFERENCES reposcope.agent_runs(run_id),
    attempt_no integer NOT NULL CHECK (attempt_no BETWEEN 1 AND 6),
    model text NOT NULL CHECK (model = 'gpt-5.6-luna'),
    estimated_input_tokens integer NOT NULL CHECK (estimated_input_tokens BETWEEN 1 AND 24000),
    max_output_tokens integer NOT NULL CHECK (max_output_tokens BETWEEN 1 AND 2000),
    reserved_usd numeric(18,6) NOT NULL CHECK (reserved_usd > 0),
    actual_input_tokens integer,
    actual_output_tokens integer,
    state text NOT NULL CHECK (state IN ('reserved','settled','uncertain')),
    budget_day date NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (run_id, attempt_no)
);
CREATE INDEX model_attempts_accounting
    ON reposcope.model_attempts (budget_day, state);
