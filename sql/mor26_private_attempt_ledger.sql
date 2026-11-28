-- MOR-26: apply once using a private, privileged PostgreSQL migration role.
-- Do NOT expose this schema via a public REST API or grant anon access.
-- Runtime roles require USAGE on schema; SELECT plus column-level
-- UPDATE(acquisition_id) on authorizations so SELECT ... FOR UPDATE may lock
-- the row (the immutable trigger rejects any actual UPDATE); SELECT/INSERT on
-- attempts, refusals and rendezvous; and
-- UPDATE(status,outcome,http_status,completed_at) on attempts.
-- Never grant runtime DELETE or authorization INSERT.
CREATE SCHEMA IF NOT EXISTS mor26_private;

CREATE TABLE IF NOT EXISTS mor26_private.authorizations (
    acquisition_id text NOT NULL,
    budget_id text NOT NULL,
    schema_version text NOT NULL CHECK(schema_version = 'physical_attempt_ledger/2'),
    budget_sha256 text NOT NULL CHECK(budget_sha256 ~ '^[a-f0-9]{64}$'),
    maximum_total_physical_attempts integer NOT NULL
        CHECK(maximum_total_physical_attempts >= 0),
    provider_ceilings_json jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (acquisition_id, budget_id)
);

CREATE TABLE IF NOT EXISTS mor26_private.attempts (
    acquisition_id text NOT NULL,
    budget_id text NOT NULL,
    seq integer NOT NULL CHECK(seq > 0),
    attempt_id text NOT NULL,
    provider text NOT NULL,
    purpose text NOT NULL CHECK(purpose IN ('health','acquisition','retry')),
    status text NOT NULL CHECK(status IN ('reserved','completed')),
    outcome text,
    http_status integer,
    reserved_at text NOT NULL,
    completed_at text,
    global_count_after integer NOT NULL CHECK(global_count_after > 0),
    provider_count_after integer NOT NULL CHECK(provider_count_after > 0),
    PRIMARY KEY(acquisition_id,budget_id,seq),
    UNIQUE(acquisition_id,budget_id,attempt_id),
    FOREIGN KEY(acquisition_id,budget_id)
        REFERENCES mor26_private.authorizations(acquisition_id,budget_id)
);

CREATE INDEX IF NOT EXISTS mor26_attempts_provider
    ON mor26_private.attempts(acquisition_id,budget_id,provider);

CREATE TABLE IF NOT EXISTS mor26_private.refusals (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    acquisition_id text NOT NULL,
    budget_id text NOT NULL,
    provider text NOT NULL,
    purpose text NOT NULL,
    reason text NOT NULL,
    refused_at text NOT NULL,
    global_count integer NOT NULL,
    provider_count integer NOT NULL,
    FOREIGN KEY(acquisition_id,budget_id)
        REFERENCES mor26_private.authorizations(acquisition_id,budget_id)
);

CREATE TABLE IF NOT EXISTS mor26_private.rendezvous (
    acquisition_id text NOT NULL,
    budget_id text NOT NULL,
    contender text NOT NULL,
    reached_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(acquisition_id,budget_id,contender),
    FOREIGN KEY(acquisition_id,budget_id)
        REFERENCES mor26_private.authorizations(acquisition_id,budget_id)
);

CREATE OR REPLACE FUNCTION mor26_private.no_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'MOR-26: authorization or reservation immutable';
END
$$;

CREATE OR REPLACE FUNCTION mor26_private.only_complete()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status <> 'reserved' OR NEW.status <> 'completed'
       OR NEW.outcome IS NULL OR NEW.completed_at IS NULL
       OR (to_jsonb(OLD) - 'status' - 'outcome' - 'http_status' - 'completed_at')
          IS DISTINCT FROM
          (to_jsonb(NEW) - 'status' - 'outcome' - 'http_status' - 'completed_at')
    THEN
        RAISE EXCEPTION 'MOR-26: counted reservation cannot be rewritten';
    END IF;
    RETURN NEW;
END
$$;

DROP TRIGGER IF EXISTS mor26_authorizations_immutable
    ON mor26_private.authorizations;
CREATE TRIGGER mor26_authorizations_immutable
    BEFORE UPDATE OR DELETE ON mor26_private.authorizations
    FOR EACH ROW EXECUTE FUNCTION mor26_private.no_mutation();

DROP TRIGGER IF EXISTS mor26_attempts_no_delete
    ON mor26_private.attempts;
CREATE TRIGGER mor26_attempts_no_delete
    BEFORE DELETE ON mor26_private.attempts
    FOR EACH ROW EXECUTE FUNCTION mor26_private.no_mutation();

DROP TRIGGER IF EXISTS mor26_attempts_only_complete
    ON mor26_private.attempts;
CREATE TRIGGER mor26_attempts_only_complete
    BEFORE UPDATE ON mor26_private.attempts
    FOR EACH ROW EXECUTE FUNCTION mor26_private.only_complete();

DROP TRIGGER IF EXISTS mor26_refusals_immutable
    ON mor26_private.refusals;
CREATE TRIGGER mor26_refusals_immutable
    BEFORE UPDATE OR DELETE ON mor26_private.refusals
    FOR EACH ROW EXECUTE FUNCTION mor26_private.no_mutation();
