"""
PostgreSQL schema definition and IAM roles for Cloud Frugality.
"""
CREATE EXTENSION IF NOT EXISTS vector;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cost_collector') THEN
        CREATE ROLE cost_collector WITH LOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cost_reader') THEN
        CREATE ROLE cost_reader WITH LOGIN;
    END IF;
END
$$;

GRANT rds_iam TO cost_collector;
GRANT rds_iam TO cost_reader;

GRANT CONNECT ON DATABASE postgres TO cost_collector;
GRANT USAGE, CREATE ON SCHEMA public TO cost_collector;

GRANT CONNECT ON DATABASE postgres TO cost_reader;
GRANT USAGE ON SCHEMA public TO cost_reader;

CREATE TABLE IF NOT EXISTS daily_cost (
    usage_date            date PRIMARY KEY,
    application_name      text          NOT NULL DEFAULT 'Frugality',
    unblended_usd         numeric(14,6) NOT NULL,
    blended_usd           numeric(14,6) NOT NULL,
    net_usd               numeric(14,6) NOT NULL,
    currency              text          NOT NULL,
    services              jsonb         NOT NULL,
    gross_usd             numeric(14,6),
    credit_usd            numeric(14,6),
    gross_services        jsonb,
    applications          jsonb,
    gross_applications    jsonb,
    plan_type             text,
    credits_granted_usd   numeric(14,2),
    credits_remaining_usd numeric(14,2),
    credits_consumed_usd  numeric(14,2),
    credits_expiry        date,
    projection            jsonb,
    change_details        text,
    change_url            text,
    collected_at          timestamptz   NOT NULL DEFAULT now()
);

GRANT SELECT, INSERT, UPDATE ON daily_cost TO cost_collector;
GRANT SELECT ON daily_cost TO cost_reader;

CREATE TABLE IF NOT EXISTS resource_inventory (
    arn               text PRIMARY KEY,
    service           text        NOT NULL,
    resource_type     text        NOT NULL,
    region            text        NOT NULL,
    application_name  text        NOT NULL DEFAULT 'Frugality',
    tags              jsonb,
    created_at        timestamptz,
    first_seen        timestamptz NOT NULL DEFAULT now(),
    last_seen         timestamptz NOT NULL DEFAULT now()
);

GRANT SELECT, INSERT, UPDATE ON resource_inventory TO cost_collector;
GRANT SELECT ON resource_inventory TO cost_reader;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE ON TABLES TO cost_collector;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT ON TABLES TO cost_reader;
