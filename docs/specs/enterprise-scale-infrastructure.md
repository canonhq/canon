---
title: "Enterprise Scale Infrastructure"
status: draft
owner: ng
team: canon
ticket_project: canonhq/canon
created: 2026-03-20
updated: 2026-03-20
tags: [enterprise, scale, infrastructure, performance, reliability]
---

# Enterprise Scale Infrastructure

Architectural changes to run Canon reliably at enterprise scale — 100+ repos, 500+ engineers, high-frequency webhook traffic, multi-replica deployments. These are platform changes that remove known bottlenecks and prepare Canon for organizations where a single GitHub App installation processes thousands of events per day.

## 1. Background

<!-- canon:system:1 status:done -->

Canon's current architecture handles small-to-medium installations well (1-20 repos, single replica). Several design decisions that were appropriate at that scale become bottlenecks for enterprise deployments:

**Synchronous webhook processing**: GitHub App webhooks are processed inline within FastAPI request handlers. A slow Claude API call or Jira API timeout blocks the webhook response. GitHub retries webhooks that don't respond within 10 seconds, creating duplicate processing. At enterprise scale (100+ repos with active development), webhook bursts can saturate the single-threaded handler.

**Sequential reverse sync**: When a Jira or Linear webhook arrives, Canon scans all repos × all spec files to find the matching spec section (`O(repos × specs)`). The code explicitly acknowledges this: `# Performance: O(repos x spec_files) sequential scan`. For an installation with 50 repos averaging 10 specs each, this is 500 file lookups per webhook.

**In-process caches**: TTL caches (org config, AI exposure, installation registry) are Python dicts local to each process. With HPA scaling to multiple replicas, each replica maintains its own cache. A config change in one replica isn't visible to others until their TTL expires, causing inconsistent behavior during the window.

**Conservative resource limits**: The Helm chart allocates 256Mi memory / 100m CPU per pod. Enterprise workloads with large spec files, vector embeddings (1024-dim float32), and concurrent Claude API calls may exceed these limits.

**Related specs:**
- `sre-alerting-monitoring.md` (draft) — observability that would surface these bottlenecks
- `enterprise-adoption-enablement.md` (draft) — features that increase load (git lifecycle sync, cross-repo queries)

## 2. Webhook Processing Queue

<!-- canon:system:2 status:todo -->

<!-- canon:ticket:jira:13 -->
Move webhook processing from synchronous request handlers to a background job queue. The webhook endpoint accepts, validates, and enqueues; workers process asynchronously.

### 2.1 Queue Architecture

Use PostgreSQL as the job queue backend (via `SELECT ... FOR UPDATE SKIP LOCKED` pattern). This avoids introducing Redis as a new dependency for the job queue use case — PostgreSQL is already required and supports reliable job queuing.

```
GitHub/Jira/Linear webhook
  → FastAPI endpoint (validate signature, enqueue, return 200)
  → PostgreSQL `webhook_jobs` table
  → Worker process (poll + process)
```

The `webhook_jobs` table:
```sql
CREATE TABLE webhook_jobs (
    id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL,           -- 'github', 'jira', 'linear'
    event_type TEXT NOT NULL,       -- 'push', 'pull_request', 'issue_update'
    payload JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',  -- 'pending', 'processing', 'done', 'failed'
    attempts INT NOT NULL DEFAULT 0,
    max_attempts INT NOT NULL DEFAULT 3,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    error TEXT,
    locked_by TEXT,                 -- worker ID for distributed locking
    locked_until TIMESTAMPTZ       -- lock expiry for crash recovery
);
CREATE INDEX idx_webhook_jobs_pending ON webhook_jobs (status, created_at) WHERE status = 'pending';
```

### 2.2 Worker Process

Workers run as a separate Deployment (or sidecar) in the Helm chart:
- Poll `webhook_jobs` with `SELECT ... FOR UPDATE SKIP LOCKED` for distributed processing
- Process one job at a time per worker (Claude API calls are the bottleneck, not CPU)
- On failure: increment `attempts`, set `status = 'failed'` if max attempts exceeded, otherwise re-queue with exponential backoff
- On crash: `locked_until` expires and the job becomes available to other workers

Worker scaling is independent of the web server — scale workers to match webhook throughput without affecting API response times.

### 2.3 Webhook Endpoint Changes

The webhook endpoints (`/webhook`, `/webhooks/jira`, `/webhooks/linear`) change from:
1. Validate signature
2. Process event (synchronous — may take 30s+ for Claude calls)
3. Return result

To:
1. Validate signature
2. Insert into `webhook_jobs`
3. Return `202 Accepted` immediately

This ensures GitHub never sees a timeout and never retries. Idempotency is handled by the job processor (existing `ON CONFLICT` patterns).

### 2.4 Graceful Degradation

If the queue is unhealthy (PostgreSQL connection lost), the webhook endpoint falls back to synchronous processing with a warning log. This ensures Canon remains functional during database issues, degrading to current behavior rather than dropping webhooks.

### Acceptance Criteria

- [ ] `webhook_jobs` table created via Alembic migration
- [ ] GitHub webhook endpoint validates and enqueues, returns 202
- [ ] Jira webhook endpoint validates and enqueues, returns 202
- [ ] Linear webhook endpoint validates and enqueues, returns 202
- [ ] Worker process polls and processes jobs from queue
- [ ] Failed jobs retried with exponential backoff up to max_attempts
- [ ] Crashed workers release locks via `locked_until` expiry
- [ ] Multiple workers process jobs concurrently without conflicts
- [ ] Helm chart includes worker Deployment with independent scaling
- [ ] Graceful fallback to synchronous processing when queue is unhealthy
- [ ] Job processing time tracked as a metric (for SRE dashboard)
- [ ] Stale/dead jobs cleaned up by scheduled maintenance (reaper CronJob or similar)

## 3. Reverse Sync Index

<!-- canon:system:3 status:todo -->

<!-- canon:ticket:jira:14 -->
Replace the sequential `O(repos × specs)` reverse sync scan with a pre-populated index that maps ticket IDs to their source spec sections.

### 3.1 Ticket Index Table

```sql
CREATE TABLE ticket_index (
    ticket_id TEXT NOT NULL,           -- 'PROJ-123', 'LIN-abc', 'GH-org/repo#45'
    ticket_system TEXT NOT NULL,       -- 'jira', 'linear', 'github'
    repo TEXT NOT NULL,                -- 'org/repo-name'
    spec_path TEXT NOT NULL,           -- 'docs/specs/feature.md'
    section_id TEXT NOT NULL,          -- '2.1'
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ticket_id, ticket_system)
);
CREATE INDEX idx_ticket_index_repo ON ticket_index (repo);
```

### 3.2 Index Population

The index is populated during forward sync:
- When the sync engine creates a ticket, it inserts a row into `ticket_index`
- When a spec section's ticket link changes, the index is updated
- When a spec or section is deleted, the corresponding index rows are removed

A one-time backfill CronJob populates the index from existing `sync_state` data for repos that were synced before this feature existed.

### 3.3 Reverse Sync Lookup

When a Jira/Linear webhook arrives with a ticket ID:
1. Query `ticket_index` for the ticket ID → get `(repo, spec_path, section_id)` in O(1)
2. Fetch only the relevant spec file from the relevant repo
3. Update the section status

This replaces the current flow of scanning all repos and all spec files. For an installation with 50 repos and 500 total specs, this reduces reverse sync from ~500 file lookups to 1 database query + 1 file lookup.

### 3.4 Index Consistency

The index is a derived cache, not a source of truth. If the index lookup misses (ticket not found), fall back to the current sequential scan and populate the index with the result. This handles edge cases where the index is stale (e.g., ticket was manually linked outside Canon).

A daily CronJob validates index consistency by sampling — comparing a random subset of index entries against actual spec files.

### Acceptance Criteria

- [ ] `ticket_index` table created via Alembic migration
- [ ] Forward sync inserts/updates index entries when creating/updating tickets
- [ ] Reverse sync uses index lookup instead of sequential scan
- [ ] Reverse sync falls back to sequential scan on index miss
- [ ] Index miss triggers index population (self-healing)
- [ ] Backfill CronJob populates index from existing `sync_state` data
- [ ] Index entries removed when spec sections or specs are deleted
- [ ] Reverse sync latency reduced by >90% for installations with 10+ repos
- [ ] Daily consistency check CronJob validates sample of index entries

## 4. Shared Cache Layer

<!-- canon:system:4 status:todo -->

<!-- canon:ticket:jira:15 -->
Replace in-process TTL caches with a shared cache for multi-replica deployments. This ensures consistent behavior across replicas and reduces redundant API calls.

### 4.1 Cache Abstraction

Introduce a `CacheBackend` interface with two implementations:

```python
class CacheBackend(Protocol):
    async def get(self, key: str) -> bytes | None: ...
    async def set(self, key: str, value: bytes, ttl: int) -> None: ...
    async def delete(self, key: str) -> None: ...

class InProcessCache(CacheBackend):
    """Default — current behavior, no external dependency."""

class RedisCache(CacheBackend):
    """Optional — shared across replicas."""
```

The `InProcessCache` remains the default for single-replica and self-hosted deployments. `RedisCache` is opt-in via configuration:

```yaml
# values.yaml
cache:
  backend: redis  # or "memory" (default)
  redis:
    url: "redis://redis:6379/0"
```

### 4.2 Cached Data

The following data currently uses in-process caches and should move to the shared cache:

| Data | Current Cache | TTL | Impact of Inconsistency |
|------|--------------|-----|------------------------|
| Org config (CANON.yaml from `.github` repo) | `_cache` in `org_config.py` | 5 min | Config changes visible on some replicas, not others |
| AI exposure decisions | `_AI_EXPOSURE_CACHE` in `mcp/server.py` | 5 min | MCP queries return different results per replica |
| GitHub file content | Various `@lru_cache` | Indefinite | Stale spec content served |
| Installation registry | In-memory lookup | Request-scoped | Minimal — already DB-backed |

Priority: org config and AI exposure caches have the highest inconsistency impact and should be migrated first.

### 4.3 Cache Invalidation

For the shared cache, add explicit invalidation hooks:
- When a `push` event includes changes to `CANON.yaml`, invalidate the org config cache for that repo
- When a `push` event includes changes to spec files, invalidate AI exposure cache entries for those specs
- Cache keys include a version/hash component to prevent stale reads after deployments

### Acceptance Criteria

- [ ] `CacheBackend` protocol defined with `get`, `set`, `delete` methods
- [ ] `InProcessCache` implementation preserves current behavior
- [ ] `RedisCache` implementation connects to configured Redis instance
- [ ] Org config cache migrated to `CacheBackend`
- [ ] AI exposure cache migrated to `CacheBackend`
- [ ] Cache backend selectable via Helm values (`cache.backend: redis | memory`)
- [ ] Redis connection included in health check (`/readyz`) when Redis backend is configured
- [ ] Push events invalidate relevant cache entries
- [ ] Cache keys include version component to prevent stale reads after deployments
- [ ] Single-replica deployments work without Redis (in-process cache is default)

## 5. Resource Scaling

<!-- canon:system:5 status:todo -->

<!-- canon:ticket:jira:16 -->
Update Helm chart resource defaults and scaling parameters for enterprise workloads.

### 5.1 Resource Limit Profiles

Define resource profiles in `values.yaml`:

```yaml
resources:
  # Default (small installations, 1-10 repos)
  requests:
    cpu: 100m
    memory: 128Mi
  limits:
    memory: 256Mi

# Suggested overrides for enterprise (documented in chart README):
# resources:
#   requests:
#     cpu: 250m
#     memory: 256Mi
#   limits:
#     memory: 512Mi
```

Document sizing guidance based on installation size:
- **Small** (1-10 repos, <20 specs): 256Mi memory, 1 replica
- **Medium** (10-50 repos, 20-100 specs): 512Mi memory, 2 replicas
- **Large** (50+ repos, 100+ specs): 1Gi memory, 3+ replicas, Redis cache, worker pool

### 5.2 HPA Tuning

Update HPA defaults for enterprise:
```yaml
autoscaling:
  enabled: false  # Default off for small installations
  minReplicas: 2
  maxReplicas: 5  # Increased from 3
  targetCPUUtilizationPercentage: 70
  targetMemoryUtilizationPercentage: 80
```

### 5.3 Worker Pool Sizing

When webhook queue is enabled (Section 2), the worker Deployment has independent scaling:
```yaml
workers:
  enabled: false  # Default off — sync processing when disabled
  replicas: 2
  resources:
    requests:
      cpu: 100m
      memory: 128Mi
    limits:
      memory: 512Mi  # Workers need memory for Claude API payloads
```

### Acceptance Criteria

- [ ] Helm chart `values.yaml` includes documented sizing guidance comments
- [ ] HPA `maxReplicas` increased to 5
- [ ] Worker Deployment added to Helm chart (disabled by default)
- [ ] Worker Deployment has independent resource limits and replica count
- [ ] Chart README documents sizing guidance for small/medium/large installations
- [ ] Memory limits tested with large spec files (100+ ACs) and concurrent Claude API calls

## Open Questions

1. **PostgreSQL vs. Redis for job queue**: This spec proposes PostgreSQL (`SELECT FOR UPDATE SKIP LOCKED`) to avoid adding a dependency. If Redis is already required for shared caching (Section 4), should the job queue also use Redis (via Redis Streams or a library like `arq`)? Recommendation: start with PostgreSQL for simplicity; migrate to Redis Streams if PostgreSQL queue becomes a bottleneck.

2. **Worker topology**: Should workers run as a separate Deployment, a sidecar container, or the same process with background threads? Separate Deployment gives independent scaling but adds operational complexity. Recommendation: separate Deployment for managed cloud, same-process background threads for self-hosted OSS (simpler).

3. **Cache warming**: Should replicas pre-warm the shared cache on startup (fetch all org configs and AI exposure decisions), or warm lazily on first access? Pre-warming reduces cold-start latency but adds startup time. Recommendation: lazy warming with a startup readiness delay.

4. **Backfill strategy for ticket index**: The one-time backfill CronJob needs to scan all repos and all specs — the same O(repos × specs) operation we're trying to eliminate. Should this run as a one-time migration, a background job, or a gradual self-healing process? Recommendation: gradual self-healing — let index misses populate the index over time, with an optional one-time backfill command for operators who want immediate coverage.
