"""Analytics dashboard API endpoints."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from ..auth.deps import require_permission
from ..auth.models import CurrentUser
from ..auth.permissions import Permission
from ..health_score import (
    compute_freshness,
    compute_health_score,
    compute_momentum,
    compute_time_to_ship,
    score_label,
)

logger = logging.getLogger(__name__)
analytics_router = APIRouter(prefix="/app")

_SAFE_PARAM = re.compile(r"^[a-zA-Z0-9_\-./]+$")


def _sanitize(value: str) -> str:
    """Validate a parameter value before embedding in HogQL."""
    if not _SAFE_PARAM.match(value):
        raise ValueError(f"Invalid parameter: {value!r}")
    return value


def _check_org_access(user: CurrentUser, org: str) -> JSONResponse | None:
    """Return a 403 JSONResponse if the authenticated user doesn't belong to *org*.

    Anonymous users (dev mode) pass through.
    """
    if user.is_anonymous:
        return None
    if not user.org_login or user.org_login != org:
        return JSONResponse({"error": "access_denied"}, status_code=403)
    return None


def _response(result: dict) -> JSONResponse:
    """Wrap a result dict in a JSONResponse with the appropriate status code.

    Expected application states (not_configured, insufficient data) return 200
    so the frontend can read the error body.  Only transient failures use 503.
    """
    if result.get("error") == "analytics_unavailable":
        return JSONResponse(result, status_code=503)
    return JSONResponse(result)


def _get_cache(request: Request):
    return request.app.state.cache


def _get_query_client(request: Request):
    return getattr(request.app.state, "posthog_query_client", None)


def _cache_key(org: str, endpoint: str, team: str, days: int) -> str:
    return f"analytics:{org}:{endpoint}:{team}:{days}"


async def _cached_query(request, org, endpoint, team, days, ttl, query_fn):
    try:
        _sanitize(org)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid org parameter") from None
    if team:
        try:
            _sanitize(team)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid team parameter") from None
    cache = _get_cache(request)
    key = _cache_key(org, endpoint, team, days)
    cached = cache.get(key)
    if cached is not None:
        return cached
    query_client = _get_query_client(request)
    if query_client is None or not query_client.configured:
        return {"error": "analytics_not_configured"}
    try:
        result = await query_fn(query_client, org, team, days)
        cache.set_with_ttl(key, result, ttl)
        return result
    except Exception:
        logger.warning("Analytics query failed for %s/%s", org, endpoint, exc_info=True)
        return {"error": "analytics_unavailable"}


# ── Query functions ────────────────────────────────────────────────────────────


def _team_filter(team: str) -> str:
    """Return a HogQL WHERE clause fragment for team filter, or empty string."""
    if team:
        return f" AND properties.team = '{_sanitize(team)}'"
    return ""


async def _query_health(query_client, org: str, team: str, days: int) -> dict:
    """Compute composite health score from momentum, freshness, and time-to-ship sub-queries."""
    org = _sanitize(org)
    tf = _team_filter(team)

    # Momentum: last 8 weeks of activity for week-over-week and 4-week average
    momentum_rows = await query_client.query(
        f"SELECT toStartOfWeek(timestamp) AS week, count() AS cnt "
        f"FROM events "
        f"WHERE properties.$group_0 = '{org}'{tf} "
        f"AND event IN ('spec_saved', 'ticket_created', 'pr_analyzed', "
        f"'ac_realized', 'mcp_tool_called') "
        f"AND timestamp >= now() - interval 8 week "
        f"GROUP BY week ORDER BY week DESC LIMIT 8"
    )

    this_week = 0
    prev_week = 0
    four_wk_avg = 0.0
    if momentum_rows:
        counts = [r["cnt"] for r in momentum_rows]
        this_week = counts[0] if len(counts) > 0 else 0
        prev_week = counts[1] if len(counts) > 1 else 0
        recent_four = counts[1:5]  # previous 4 weeks, excluding this_week
        four_wk_avg = sum(recent_four) / len(recent_four) if recent_four else 0.0

    momentum_score = compute_momentum(this_week, prev_week, four_wk_avg)

    # Freshness: staleness of specs
    freshness_rows = await query_client.query(
        f"SELECT properties.spec_id AS spec_id, "
        f"  max(timestamp) AS last_updated, "
        f"  count() AS ac_count "
        f"FROM events "
        f"WHERE event = 'ac_realized' "
        f"AND properties.$group_0 = '{org}'{tf} "
        f"GROUP BY spec_id"
    )

    specs_for_freshness = []
    now_ts = datetime.now(UTC)
    for row in freshness_rows:
        try:
            last_updated = row.get("last_updated")
            if isinstance(last_updated, str):
                last_updated = datetime.fromisoformat(last_updated.replace("Z", "+00:00"))
            if last_updated and hasattr(last_updated, "tzinfo"):
                if last_updated.tzinfo is None:
                    last_updated = last_updated.replace(tzinfo=UTC)
                gap_days = max(0, (now_ts - last_updated).days)
            else:
                gap_days = 30
            specs_for_freshness.append(
                {
                    "staleness_gap": gap_days,
                    "ac_count": int(row.get("ac_count", 1)),
                }
            )
        except (ValueError, TypeError, KeyError) as exc:
            logger.warning("Skipping unparseable freshness row %r: %s", row, exc)

    freshness_score = compute_freshness(specs_for_freshness)

    # Time to ship: average cycle time over current period vs baseline
    cycle_rows = await query_client.query(
        f"SELECT avg(toFloatOrDefault(properties.cycle_time_days)) AS avg_cycle "
        f"FROM events "
        f"WHERE event = 'spec_shipped' "
        f"AND properties.$group_0 = '{org}'{tf} "
        f"AND timestamp >= now() - interval {days} day"
    )
    baseline_rows = await query_client.query(
        f"SELECT avg(toFloatOrDefault(properties.cycle_time_days)) AS avg_cycle "
        f"FROM events "
        f"WHERE event = 'spec_shipped' "
        f"AND properties.$group_0 = '{org}'{tf} "
        f"AND timestamp < now() - interval {days} day "
        f"AND timestamp >= now() - interval {days * 2} day"
    )

    current_cycle = float((cycle_rows[0].get("avg_cycle") or 0) if cycle_rows else 0)
    baseline_cycle = float((baseline_rows[0].get("avg_cycle") or 0) if baseline_rows else 0)
    time_to_ship_score = compute_time_to_ship(current_cycle, baseline_cycle)

    composite = compute_health_score(momentum_score, freshness_score, time_to_ship_score)

    # Compute deltas (momentum: wow change, freshness/tts: period-over-period)
    momentum_delta = None
    if prev_week > 0 and this_week > 0:
        momentum_delta = round((this_week - prev_week) / prev_week * 100, 1)

    tts_delta = None
    if baseline_cycle > 0 and current_cycle > 0:
        tts_delta = round((baseline_cycle - current_cycle) / baseline_cycle * 100, 1)

    # Trend: last 4 weeks of composite-like activity counts for sparkline
    trend_rows = await query_client.query(
        f"SELECT toStartOfWeek(timestamp) AS week, count() AS cnt "
        f"FROM events "
        f"WHERE properties.$group_0 = '{org}'{tf} "
        f"AND timestamp >= now() - interval 4 week "
        f"GROUP BY week ORDER BY week ASC LIMIT 4"
    )
    trend = [{"date": str(r.get("week", "")), "score": r.get("cnt", 0)} for r in trend_rows]

    def _pillar_summary(name: str, score) -> str:
        if score is None:
            return f"No {name} data yet"
        label = score_label(score)
        return f"{name.replace('_', ' ').title()}: {label} ({score:.0f})"

    return {
        "score": composite,
        "label": score_label(composite),
        "pillars": {
            "momentum": {
                "score": momentum_score,
                "delta": momentum_delta,
                "summary": _pillar_summary("momentum", momentum_score),
            },
            "freshness": {
                "score": freshness_score,
                "delta": None,
                "summary": _pillar_summary("freshness", freshness_score),
            },
            "time_to_ship": {
                "score": time_to_ship_score,
                "delta": tts_delta,
                "summary": _pillar_summary("time_to_ship", time_to_ship_score),
            },
        },
        "trend": trend,
    }


async def _query_momentum(query_client, org: str, team: str, days: int) -> dict:
    """Return weekly activity time-series and top repos by activity."""
    org = _sanitize(org)
    tf = _team_filter(team)

    weekly_rows = await query_client.query(
        f"SELECT toStartOfWeek(timestamp) AS week, event AS event_type, count() AS cnt "
        f"FROM events "
        f"WHERE properties.$group_0 = '{org}'{tf} "
        f"AND timestamp >= now() - interval {days} day "
        f"GROUP BY week, event_type ORDER BY week ASC"
    )
    weekly_activity = [
        {
            "week": str(r.get("week", "")),
            "event_type": r.get("event_type", ""),
            "count": r.get("cnt", 0),
        }
        for r in weekly_rows
    ]

    repo_rows = await query_client.query(
        f"SELECT properties.repo AS repo, count() AS cnt "
        f"FROM events "
        f"WHERE properties.$group_0 = '{org}'{tf} "
        f"AND timestamp >= now() - interval {days} day "
        f"AND properties.repo IS NOT NULL "
        f"GROUP BY repo ORDER BY cnt DESC LIMIT 10"
    )
    top_repos = [{"repo": r.get("repo", ""), "count": r.get("cnt", 0)} for r in repo_rows]

    return {
        "weekly_activity": weekly_activity,
        "top_repos": top_repos,
        "top_contributors": [],
    }


async def _query_freshness(query_client, org: str, team: str, days: int) -> dict:
    """Return per-spec freshness data and a summary."""
    org = _sanitize(org)
    tf = _team_filter(team)

    rows = await query_client.query(
        f"SELECT properties.spec_id AS spec_id, "
        f"  properties.repo AS repo, "
        f"  max(timestamp) AS last_updated, "
        f"  count() AS ac_count "
        f"FROM events "
        f"WHERE event = 'ac_realized' "
        f"AND properties.$group_0 = '{org}'{tf} "
        f"GROUP BY spec_id, repo "
        f"ORDER BY last_updated ASC"
    )

    # Query for last code change per spec
    code_rows = await query_client.query(
        f"SELECT properties.spec_id AS spec_id, "
        f"  max(timestamp) AS last_code_change "
        f"FROM events "
        f"WHERE event = 'pr_analyzed' "
        f"AND properties.$group_0 = '{org}'{tf} "
        f"GROUP BY spec_id"
    )
    code_change_map: dict[str, Any] = {}
    for r in code_rows:
        sid = r.get("spec_id", "")
        if sid:
            code_change_map[sid] = r.get("last_code_change")

    now_ts = datetime.now(UTC)
    specs = []
    total_gap = 0.0

    for row in rows:
        try:
            last_updated = row.get("last_updated")
            if isinstance(last_updated, str):
                last_updated = datetime.fromisoformat(last_updated.replace("Z", "+00:00"))
            if last_updated and hasattr(last_updated, "tzinfo"):
                if last_updated.tzinfo is None:
                    last_updated = last_updated.replace(tzinfo=UTC)
                gap_days = max(0, (now_ts - last_updated).days)
            else:
                gap_days = 30

            spec_id = row.get("spec_id", "")

            # Compute days_since_code from code_change_map
            days_since_code = 0
            code_ts = code_change_map.get(spec_id)
            if code_ts:
                if isinstance(code_ts, str):
                    code_ts = datetime.fromisoformat(code_ts.replace("Z", "+00:00"))
                if code_ts and hasattr(code_ts, "tzinfo"):
                    if code_ts.tzinfo is None:
                        code_ts = code_ts.replace(tzinfo=UTC)
                    days_since_code = max(0, (now_ts - code_ts).days)

            freshness = 100.0 if gap_days <= 7 else max(0.0, 100.0 - (gap_days - 7) * 5)
            specs.append(
                {
                    "spec_path": spec_id,
                    "repo": row.get("repo", ""),
                    "freshness_score": freshness,
                    "days_since_update": gap_days,
                    "days_since_code": days_since_code,
                }
            )
            total_gap += gap_days
        except (ValueError, TypeError, KeyError):
            logger.warning("Skipping malformed freshness row: %s", row, exc_info=True)

    stale_count = sum(1 for s in specs if s["days_since_update"] > 14)
    fresh_count = len(specs) - stale_count
    avg_gap_days = total_gap / len(specs) if specs else 0.0

    return {
        "specs": specs,
        "summary": {
            "fresh_count": fresh_count,
            "stale_count": stale_count,
            "avg_gap_days": round(avg_gap_days, 1),
        },
    }


async def _query_time_to_ship(query_client, org: str, team: str, days: int) -> dict:
    """Return cycle time breakdown by spec stage."""
    org = _sanitize(org)
    tf = _team_filter(team)

    # Current period stages
    rows = await query_client.query(
        f"SELECT properties.stage AS stage, "
        f"  median(toFloatOrDefault(properties.duration_days)) AS median_days, "
        f"  count() AS count "
        f"FROM events "
        f"WHERE event = 'spec_stage_completed' "
        f"AND properties.$group_0 = '{org}'{tf} "
        f"AND timestamp >= now() - interval {days} day "
        f"GROUP BY stage ORDER BY median_days DESC"
    )

    # Previous period stages for trend calculation
    prev_rows = await query_client.query(
        f"SELECT properties.stage AS stage, "
        f"  median(toFloatOrDefault(properties.duration_days)) AS median_days "
        f"FROM events "
        f"WHERE event = 'spec_stage_completed' "
        f"AND properties.$group_0 = '{org}'{tf} "
        f"AND timestamp < now() - interval {days} day "
        f"AND timestamp >= now() - interval {days * 2} day "
        f"GROUP BY stage"
    )
    prev_map = {r.get("stage", ""): float(r.get("median_days") or 0) for r in prev_rows}

    stages = []
    total_cycle_days = 0.0
    for r in rows:
        stage_name = r.get("stage", "")
        med = float(r.get("median_days") or 0)
        total_cycle_days += med
        prev_med = prev_map.get(stage_name, 0)
        trend_pct = 0.0
        if prev_med > 0:
            trend_pct = round((med - prev_med) / prev_med * 100, 1)
        stages.append(
            {
                "name": stage_name,
                "median_days": med,
                "trend_pct": trend_pct,
            }
        )

    # Overall improvement: compare total current cycle vs previous
    total_prev_cycle = sum(prev_map.values())
    improvement_pct = 0.0
    if total_prev_cycle > 0 and total_cycle_days > 0:
        improvement_pct = round((total_prev_cycle - total_cycle_days) / total_prev_cycle * 100, 1)

    # Weekly trend
    trend_rows = await query_client.query(
        f"SELECT toStartOfWeek(timestamp) AS week, "
        f"  avg(toFloatOrDefault(properties.duration_days)) AS total_cycle "
        f"FROM events "
        f"WHERE event = 'spec_stage_completed' "
        f"AND properties.$group_0 = '{org}'{tf} "
        f"AND timestamp >= now() - interval {days} day "
        f"GROUP BY week ORDER BY week ASC"
    )
    trend = [
        {"week": str(r.get("week", "")), "total_cycle": float(r.get("total_cycle") or 0)}
        for r in trend_rows
    ]

    return {
        "stages": stages,
        "total_cycle_days": round(total_cycle_days, 1),
        "improvement_pct": improvement_pct,
        "trend": trend,
    }


async def _query_feature_usage(query_client, org: str, team: str, days: int) -> dict:
    """Return feature adoption metrics for admin view."""
    # Feature usage always uses a fixed 30-day window regardless of the days
    # parameter (required by the _cached_query interface but unused here).
    org = _sanitize(org)
    tf = _team_filter(team)

    rows = await query_client.query(
        f"SELECT event AS feature, count() AS uses, "
        f"  count(DISTINCT properties.repo) AS repo_count "
        f"FROM events "
        f"WHERE properties.$group_0 = '{org}'{tf} "
        f"AND timestamp >= now() - interval 30 day "
        f"GROUP BY feature ORDER BY uses DESC LIMIT 50"
    )

    # Get total repos count for percentage calculation
    total_repos_rows = await query_client.query(
        f"SELECT count(DISTINCT properties.repo) AS total "
        f"FROM events "
        f"WHERE properties.$group_0 = '{org}'{tf} "
        f"AND timestamp >= now() - interval 30 day"
    )
    total_repos = int((total_repos_rows[0].get("total") or 0) if total_repos_rows else 0)

    # Get repos with/without config
    config_rows = await query_client.query(
        f"SELECT count(DISTINCT properties.repo) AS cnt "
        f"FROM events "
        f"WHERE properties.$group_0 = '{org}'{tf} "
        f"AND event = 'config_loaded' "
        f"AND timestamp >= now() - interval 30 day"
    )
    repos_with_config = int((config_rows[0].get("cnt") or 0) if config_rows else 0)

    features = []
    for r in rows:
        enabled = int(r.get("repo_count") or 0)
        pct = round(enabled / total_repos * 100, 1) if total_repos > 0 else 0.0
        features.append(
            {
                "name": r.get("feature", ""),
                "enabled_count": enabled,
                "total_repos": total_repos,
                "pct": pct,
            }
        )

    return {
        "features": features,
        "repos_with_config": repos_with_config,
        "repos_without_config": max(0, total_repos - repos_with_config),
    }


# ── Endpoints ──────────────────────────────────────────────────────────────────


@analytics_router.get("/{org}/api/analytics/health", response_class=JSONResponse)
async def api_analytics_health(
    request: Request,
    org: str,
    team: str = "",
    days: int = Query(default=30, ge=1, le=365),
    _user: CurrentUser = Depends(require_permission(Permission.SPECS_READ)),
) -> JSONResponse:
    denied = _check_org_access(_user, org)
    if denied:
        return denied
    result = await _cached_query(request, org, "health", team, days, 3600, _query_health)
    return _response(result)


@analytics_router.get("/{org}/api/analytics/momentum", response_class=JSONResponse)
async def api_analytics_momentum(
    request: Request,
    org: str,
    team: str = "",
    days: int = Query(default=30, ge=1, le=365),
    _user: CurrentUser = Depends(require_permission(Permission.SPECS_READ)),
) -> JSONResponse:
    denied = _check_org_access(_user, org)
    if denied:
        return denied
    result = await _cached_query(request, org, "momentum", team, days, 900, _query_momentum)
    return _response(result)


@analytics_router.get("/{org}/api/analytics/freshness", response_class=JSONResponse)
async def api_analytics_freshness(
    request: Request,
    org: str,
    team: str = "",
    days: int = Query(default=30, ge=1, le=365),
    _user: CurrentUser = Depends(require_permission(Permission.SPECS_READ)),
) -> JSONResponse:
    denied = _check_org_access(_user, org)
    if denied:
        return denied
    result = await _cached_query(request, org, "freshness", team, days, 900, _query_freshness)
    return _response(result)


@analytics_router.get("/{org}/api/analytics/time-to-ship", response_class=JSONResponse)
async def api_analytics_time_to_ship(
    request: Request,
    org: str,
    team: str = "",
    days: int = Query(default=30, ge=1, le=365),
    _user: CurrentUser = Depends(require_permission(Permission.SPECS_READ)),
) -> JSONResponse:
    denied = _check_org_access(_user, org)
    if denied:
        return denied
    result = await _cached_query(request, org, "time-to-ship", team, days, 900, _query_time_to_ship)
    return _response(result)


@analytics_router.get("/{org}/api/analytics/feature-usage", response_class=JSONResponse)
async def api_analytics_feature_usage(
    request: Request,
    org: str,
    _user: CurrentUser = Depends(require_permission(Permission.SPECS_ADMIN)),
) -> JSONResponse:
    denied = _check_org_access(_user, org)
    if denied:
        return denied
    result = await _cached_query(request, org, "feature-usage", "", 0, 3600, _query_feature_usage)
    return _response(result)
