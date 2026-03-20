"""Baseline schema — consolidated from schema*.sql files.

Revision ID: 0001
Revises: None
Create Date: 2026-03-17
"""

from __future__ import annotations

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # --- Extensions ---
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # --- schema.sql: spec_documents + spec_sections ---
    op.execute("""
        CREATE TABLE IF NOT EXISTS spec_documents (
            id              BIGSERIAL PRIMARY KEY,
            repo            TEXT NOT NULL,
            path            TEXT NOT NULL,
            title           TEXT NOT NULL DEFAULT '',
            status          TEXT NOT NULL DEFAULT '',
            content_hash    TEXT NOT NULL DEFAULT '',
            commit_sha      TEXT NOT NULL DEFAULT '',
            doc_type        TEXT NOT NULL DEFAULT 'spec',
            last_code_change_at TIMESTAMPTZ,
            last_doc_change_at  TIMESTAMPTZ,
            stale_since     TIMESTAMPTZ,
            embedding       vector(1024),
            indexed_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (repo, path)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS spec_sections (
            id              BIGSERIAL PRIMARY KEY,
            document_id     BIGINT NOT NULL REFERENCES spec_documents(id) ON DELETE CASCADE,
            heading         TEXT NOT NULL DEFAULT '',
            level           INT NOT NULL DEFAULT 1,
            body            TEXT NOT NULL DEFAULT '',
            status          TEXT NOT NULL DEFAULT '',
            ticket_ref      TEXT NOT NULL DEFAULT '',
            embedding       vector(1024),
            indexed_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_spec_documents_repo ON spec_documents (repo)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_spec_sections_document_id ON spec_sections (document_id)"
    )
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_spec_documents_embedding
            ON spec_documents USING hnsw (embedding vector_cosine_ops)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_spec_sections_embedding
            ON spec_sections USING hnsw (embedding vector_cosine_ops)
    """)

    # --- schema_installations.sql: gh_installations + index_jobs ---
    op.execute("""
        CREATE TABLE IF NOT EXISTS gh_installations (
            id              BIGSERIAL PRIMARY KEY,
            installation_id BIGINT NOT NULL UNIQUE,
            org_login       TEXT NOT NULL,
            org_id          BIGINT NOT NULL DEFAULT 0,
            app_id          TEXT NOT NULL DEFAULT '',
            status          TEXT NOT NULL DEFAULT 'active',
            installed_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_indexed_at TIMESTAMPTZ,
            repos_count     INT NOT NULL DEFAULT 0,
            oidc_org_id     TEXT NOT NULL DEFAULT ''
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_gh_installations_org_login ON gh_installations (org_login)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_gh_installations_status ON gh_installations (status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_gh_installations_oidc_org_id "
        "ON gh_installations (oidc_org_id) WHERE oidc_org_id != ''"
    )
    op.execute("""
        CREATE TABLE IF NOT EXISTS index_jobs (
            id              BIGSERIAL PRIMARY KEY,
            installation_id BIGINT NOT NULL,
            repo            TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'pending',
            started_at      TIMESTAMPTZ,
            completed_at    TIMESTAMPTZ,
            specs_indexed   INT NOT NULL DEFAULT 0,
            errors          INT NOT NULL DEFAULT 0,
            error_message   TEXT NOT NULL DEFAULT ''
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_index_jobs_installation_id ON index_jobs (installation_id)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_index_jobs_status ON index_jobs (status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_index_jobs_repo ON index_jobs (repo)")

    # --- schema_agent.sql: agent_events, realization_evidence, sync_state ---
    op.execute("""
        CREATE TABLE IF NOT EXISTS agent_events (
            id BIGSERIAL PRIMARY KEY,
            repo TEXT NOT NULL,
            event_type TEXT NOT NULL,
            pr_number INT,
            issue_number INT,
            actor TEXT NOT NULL DEFAULT '',
            detail JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_agent_events_repo ON agent_events (repo)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_events_event_type ON agent_events (event_type)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_events_created_at ON agent_events (created_at)"
    )
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_agent_events_pr_number ON agent_events (pr_number)
            WHERE pr_number IS NOT NULL
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS realization_evidence (
            id BIGSERIAL PRIMARY KEY,
            repo TEXT NOT NULL,
            spec_path TEXT NOT NULL,
            section_id TEXT NOT NULL,
            ac_text TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'not_addressed',
            pr_number INT NOT NULL,
            pr_url TEXT NOT NULL DEFAULT '',
            evidence_files JSONB NOT NULL DEFAULT '[]',
            assessed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (repo, spec_path, section_id, ac_text, pr_number)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_realization_evidence_repo ON realization_evidence (repo)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_realization_evidence_spec "
        "ON realization_evidence (repo, spec_path)"
    )
    op.execute("""
        CREATE TABLE IF NOT EXISTS sync_state (
            id BIGSERIAL PRIMARY KEY,
            repo TEXT NOT NULL,
            spec_path TEXT NOT NULL,
            section_id TEXT NOT NULL,
            ticket_id TEXT NOT NULL,
            last_synced_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_status TEXT NOT NULL DEFAULT '',
            UNIQUE (repo, spec_path, section_id, ticket_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_sync_state_repo ON sync_state (repo)")

    # --- schema_users.sql: users, api_keys, sessions ---
    op.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id              BIGSERIAL PRIMARY KEY,
            oidc_sub        TEXT NOT NULL UNIQUE,
            email           TEXT NOT NULL DEFAULT '',
            name            TEXT NOT NULL DEFAULT '',
            picture         TEXT NOT NULL DEFAULT '',
            role            TEXT NOT NULL DEFAULT 'editor',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_login_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users (email)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS api_keys (
            id              BIGSERIAL PRIMARY KEY,
            key_hash        TEXT NOT NULL UNIQUE,
            label           TEXT NOT NULL DEFAULT '',
            user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            org_login       TEXT NOT NULL,
            scopes          TEXT[] NOT NULL DEFAULT '{}',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at      TIMESTAMPTZ,
            revoked_at      TIMESTAMPTZ,
            last_used_at    TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_api_keys_user_id ON api_keys (user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_api_keys_org_login ON api_keys (org_login)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_api_keys_key_hash ON api_keys (key_hash)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id              TEXT PRIMARY KEY,
            user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            org_login       TEXT NOT NULL,
            device_label    TEXT NOT NULL DEFAULT '',
            refresh_hash    TEXT NOT NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_used_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at      TIMESTAMPTZ NOT NULL,
            revoked_at      TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions (user_id)")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_refresh_hash ON sessions (refresh_hash)"
    )

    # --- schema_coverage.sql: coverage_snapshots ---
    op.execute("""
        CREATE TABLE IF NOT EXISTS coverage_snapshots (
            id              BIGSERIAL PRIMARY KEY,
            snapshot_date   DATE NOT NULL,
            org             TEXT NOT NULL,
            repo            TEXT NOT NULL,
            team            TEXT NOT NULL DEFAULT '',
            spec_path       TEXT NOT NULL DEFAULT '',
            total_sections  INT NOT NULL DEFAULT 0,
            done_sections   INT NOT NULL DEFAULT 0,
            total_ac        INT NOT NULL DEFAULT 0,
            done_ac         INT NOT NULL DEFAULT 0,
            realized_ac     INT NOT NULL DEFAULT 0,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (snapshot_date, org, repo, spec_path)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_coverage_snapshots_org ON coverage_snapshots (org)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_coverage_snapshots_date "
        "ON coverage_snapshots (snapshot_date)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_coverage_snapshots_org_repo "
        "ON coverage_snapshots (org, repo)"
    )

    # --- schema_billing.sql: subscriptions, seat_activity, ai_op_usage, etc. ---
    op.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_login       TEXT NOT NULL UNIQUE,
            stripe_customer_id TEXT UNIQUE,
            stripe_subscription_id TEXT UNIQUE,
            plan            TEXT NOT NULL CHECK (plan IN ('starter', 'pro', 'enterprise')),
            billing_cycle   TEXT NOT NULL CHECK (billing_cycle IN ('monthly', 'annual')),
            status          TEXT NOT NULL DEFAULT 'active'
                            CHECK (status IN ('active', 'past_due', 'canceled', 'trialing')),
            seat_count      INTEGER NOT NULL DEFAULT 3 CHECK (seat_count >= 3),
            current_period_start TIMESTAMPTZ,
            current_period_end TIMESTAMPTZ,
            trial_start     TIMESTAMPTZ,
            trial_end       TIMESTAMPTZ,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_subscriptions_org ON subscriptions (org_login)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS seat_activity (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_login       TEXT NOT NULL,
            user_login      TEXT NOT NULL,
            activity_type   TEXT NOT NULL,
            recorded_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (org_login, user_login, activity_type, recorded_at)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_seat_activity_org_period "
        "ON seat_activity (org_login, recorded_at)"
    )
    op.execute("""
        CREATE TABLE IF NOT EXISTS ai_op_usage (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_login       TEXT NOT NULL,
            op_type         TEXT NOT NULL,
            user_login      TEXT NOT NULL DEFAULT '',
            repo            TEXT NOT NULL DEFAULT '',
            recorded_at     TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_op_usage_org_period "
        "ON ai_op_usage (org_login, recorded_at)"
    )
    op.execute("""
        CREATE TABLE IF NOT EXISTS ai_op_monthly_summary (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_login       TEXT NOT NULL,
            period_start    TIMESTAMPTZ NOT NULL,
            period_end      TIMESTAMPTZ NOT NULL,
            ops_used        INTEGER NOT NULL DEFAULT 0,
            ops_included    INTEGER NOT NULL DEFAULT 0,
            overage_billed  BOOLEAN NOT NULL DEFAULT FALSE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (org_login, period_start)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS billing_events (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_login       TEXT NOT NULL,
            stripe_event_id TEXT NOT NULL UNIQUE,
            event_type      TEXT NOT NULL,
            payload         JSONB NOT NULL,
            status          TEXT NOT NULL DEFAULT 'processing',
            processed_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_billing_events_org ON billing_events (org_login)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS anthropic_keys (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_login       TEXT NOT NULL UNIQUE,
            encrypted_key   BYTEA NOT NULL,
            key_suffix      TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'invalid')),
            last_validated_at TIMESTAMPTZ,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS enterprise_contacts (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name            TEXT NOT NULL,
            email           TEXT NOT NULL,
            company         TEXT NOT NULL,
            team_size       TEXT NOT NULL,
            message         TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)


def downgrade() -> None:
    # Drop in reverse dependency order
    op.execute("DROP TABLE IF EXISTS enterprise_contacts")
    op.execute("DROP TABLE IF EXISTS anthropic_keys")
    op.execute("DROP TABLE IF EXISTS billing_events")
    op.execute("DROP TABLE IF EXISTS ai_op_monthly_summary")
    op.execute("DROP TABLE IF EXISTS ai_op_usage")
    op.execute("DROP TABLE IF EXISTS seat_activity")
    op.execute("DROP TABLE IF EXISTS subscriptions")
    op.execute("DROP TABLE IF EXISTS coverage_snapshots")
    op.execute("DROP TABLE IF EXISTS sessions")
    op.execute("DROP TABLE IF EXISTS api_keys")
    op.execute("DROP TABLE IF EXISTS users")
    op.execute("DROP TABLE IF EXISTS sync_state")
    op.execute("DROP TABLE IF EXISTS realization_evidence")
    op.execute("DROP TABLE IF EXISTS agent_events")
    op.execute("DROP TABLE IF EXISTS index_jobs")
    op.execute("DROP TABLE IF EXISTS gh_installations")
    op.execute("DROP TABLE IF EXISTS spec_sections")
    op.execute("DROP TABLE IF EXISTS spec_documents")
