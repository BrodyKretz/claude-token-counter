"""Per-day usage buckets, and the views built from them (breakdown, models,
projects, history).

state["daily"] maps an ISO date to:
    {
        "models": {model_id: {category: tokens, ...}, ...},
        "projects": {project_label: tokens, ...},
    }
where category is one of CATEGORIES. Everything the menu shows (today,
by model, by project, history, cost) is derived from these buckets.
"""

from datetime import date, datetime, timedelta
from pathlib import Path

CATEGORIES = ["input", "output", "cache_write_5m", "cache_write_1h", "cache_read"]

WORKTREE_MARKER = "/.claude/worktrees/"


def _local_date_of(timestamp_str):
    utc_dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
    return utc_dt.astimezone().date()


def split_usage(usage):
    """Split one API usage object into CATEGORIES token counts."""
    cache_write = usage.get("cache_creation_input_tokens", 0) or 0
    detail = usage.get("cache_creation") or {}
    write_1h = min(detail.get("ephemeral_1h_input_tokens", 0) or 0, cache_write)
    return {
        "input": usage.get("input_tokens", 0) or 0,
        "output": usage.get("output_tokens", 0) or 0,
        "cache_write_5m": cache_write - write_1h,
        "cache_write_1h": write_1h,
        "cache_read": usage.get("cache_read_input_tokens", 0) or 0,
    }


def project_label(cwd, home=None):
    """Human-readable project name for a session's working directory.

    Agent worktrees (<project>/.claude/worktrees/<id>) are folded into the
    project they belong to.
    """
    if not cwd:
        return "Unknown"
    if WORKTREE_MARKER in cwd:
        cwd = cwd.split(WORKTREE_MARKER, 1)[0]
    home = str(home or Path.home())
    if cwd == home:
        return "~"
    if cwd.startswith(home + "/"):
        return "~/" + cwd[len(home) + 1 :]
    return cwd


def record_entry(daily, entry):
    """Add one parsed assistant log entry to the daily buckets."""
    usage = entry.get("message", {}).get("usage")
    timestamp = entry.get("timestamp")
    if not usage or not timestamp:
        return
    parts = split_usage(usage)
    tokens = sum(parts.values())
    if tokens == 0:
        return
    day = daily.setdefault(
        _local_date_of(timestamp).isoformat(), {"models": {}, "projects": {}}
    )
    model = entry.get("message", {}).get("model") or "unknown"
    bucket = day["models"].setdefault(model, {c: 0 for c in CATEGORIES})
    for category, count in parts.items():
        bucket[category] = bucket.get(category, 0) + count
    project = project_label(entry.get("cwd"))
    day["projects"][project] = day["projects"].get(project, 0) + tokens


def _days_in_range(daily, start, end):
    """Buckets for dates in [start, end], inclusive."""
    for iso, bucket in daily.items():
        if start <= date.fromisoformat(iso) <= end:
            yield bucket


def models_in_range(daily, start, end):
    """{model: {category: tokens}} summed over [start, end]."""
    totals = {}
    for bucket in _days_in_range(daily, start, end):
        for model, parts in bucket["models"].items():
            into = totals.setdefault(model, {c: 0 for c in CATEGORIES})
            for category in CATEGORIES:
                into[category] += parts.get(category, 0)
    return totals


def models_all_time(daily):
    return models_in_range(daily, date.min, date.max)


def category_totals(models):
    """{category: tokens} summed across models."""
    return {c: sum(parts.get(c, 0) for parts in models.values()) for c in CATEGORIES}


def model_totals(models):
    """[(model, tokens)] sorted by tokens, most first."""
    rows = [(m, sum(parts.values())) for m, parts in models.items()]
    return sorted(rows, key=lambda r: r[1], reverse=True)


def total_in_range(daily, start, end):
    return sum(t for _, t in model_totals(models_in_range(daily, start, end)))


def _fold_subfolders(totals):
    """Merge a subfolder's tokens into its parent when the parent is also a
    project (e.g. "~/game/tools" into "~/game")."""
    folded = {}
    for project in sorted(totals, key=len):
        parent = next(
            (p for p in folded if project.startswith(p.rstrip("/") + "/")), None
        )
        key = parent or project
        folded[key] = folded.get(key, 0) + totals[project]
    return folded


def top_projects(daily, start, end, limit=3):
    totals = {}
    for bucket in _days_in_range(daily, start, end):
        for project, tokens in bucket["projects"].items():
            totals[project] = totals.get(project, 0) + tokens
    totals = _fold_subfolders(totals)
    rows = sorted(totals.items(), key=lambda r: r[1], reverse=True)
    return rows[:limit]


def biggest_day(daily):
    """(date, tokens) of the highest-usage day, or None if no data."""
    best = None
    for iso, bucket in daily.items():
        tokens = sum(sum(p.values()) for p in bucket["models"].values())
        if best is None or tokens > best[1]:
            best = (date.fromisoformat(iso), tokens)
    return best


def history(daily, today=None):
    """Totals for the History menu."""
    today = today or date.today()
    yesterday = today - timedelta(days=1)
    return {
        "yesterday": total_in_range(daily, yesterday, yesterday),
        "last_7_days": total_in_range(daily, today - timedelta(days=6), today),
        "this_month": total_in_range(daily, today.replace(day=1), today),
        "biggest_day": biggest_day(daily),
    }
