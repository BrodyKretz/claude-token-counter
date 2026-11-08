# Multi-tool tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Track Codex and opencode alongside Claude Code, one tool at a time by default, with a combined all-models view, a first-run tool picker, and Settings switches.

**Architecture:** Each new tool gets a reader module that turns its on-disk data into the same per-day buckets Claude Code already uses, stored under `state["sources"][tool]`. A small registry (`tools.py`) detects tools, runs their scans, and hands the panel a "view" (per-day buckets + lifetime total) for the selected tool or for all tools merged. The panel gains a tool switcher and a welcome view.

**Tech Stack:** Python 3, rumps + PyObjC (AppKit), sqlite3 (stdlib), pytest.

**Spec:** `docs/superpowers/specs/2026-11-07-multi-tool-tracking-design.md`

## Global Constraints

- Claude Code's existing state keys (`grand_total`, `file_offsets`, `daily`, `daily_backfilled`, `first_seen_at`) and every existing preference key keep their names and values; nothing migrates them.
- Existing installs (a `state.json` already exists) start with `enabled_tools = ["claude_code"]`, `combine_tools = False`, and never see the welcome view.
- Fresh installs start with `enabled_tools = []` and open the welcome view; nothing is scanned until tools are chosen.
- Tool keys and display names: `claude_code` "Claude Code", `codex` "Codex", `opencode` "opencode".
- Readers take only token counts, model, timestamp and project folder. opencode is opened read-only (`file:...?mode=ro` URI) and only `session_message` and `session_v2` are queried.
- Codex `input_tokens` includes `cached_input_tokens`: input = input − cached, cache_read = cached, cache_write_5m = `cache_write_input_tokens`, output = `output_tokens`.
- opencode: input = `tokens.input`, output = `tokens.output + tokens.reasoning`, cache_read = `tokens.cache.read`, cache_write_5m = `tokens.cache.write`.
- Leaderboard stays Claude Code only.

## Review Focus

- A Codex log being written while scanned (last line incomplete) must not crash or count a half line; the next scan picks it up.
- opencode's database busy/locked or schema changed: that tool shows "couldn't be read", saved history stays, other tools unaffected.
- A tool's data folder disappears after it was enabled: its saved history and lifetime total remain.
- Fresh install where no other tool is detected: the welcome view still lists Claude Code (if detected) or says no supported tools were found, and Continue works.
- Upgrading an existing install leaves every existing state value byte-for-byte equal except new keys added.

---

### Task 1: Shared bucket helpers

**Files:**
- Modify: `usage_stats.py`
- Test: `tests/test_usage_stats.py`

**Interfaces:**
- Produces: `add_usage(daily: dict, day: date, model: str, project: str, parts: dict, cost: float | None = None) -> None` (adds token parts into `daily[iso]["models"][model]`, tokens into `daily[iso]["projects"][project]`, and, if `cost` is given, into `daily[iso]["recorded_cost"][model]`); `merge_daily(dailies: list[dict]) -> dict` (sums buckets); `merge_max_daily(saved: dict, current: dict) -> dict` (per day/model/category/project/cost takes the larger value); `recorded_cost_in_range(daily, start, end) -> dict[str, float]`.

- [ ] **Step 1: Write failing tests** `test_add_usage_creates_and_sums_buckets`, `test_merge_daily_sums_across_tools`, `test_merge_max_daily_never_shrinks` (saved 10 vs current 4 → 10; new day in current appears), `test_recorded_cost_in_range`.
- [ ] **Step 2: Run** `pytest tests/test_usage_stats.py -q` → the four new tests fail.
- [ ] **Step 3: Implement** the four functions; `record_entry` reuses `add_usage`. Existing views ignore `recorded_cost`.
- [ ] **Step 4: Run** the full suite → all pass.
- [ ] **Step 5: Commit** `Add shared per-day bucket helpers for more tools`.

### Task 2: Codex reader

**Files:**
- Create: `codex_source.py`
- Test: `tests/test_codex_source.py`

**Interfaces:**
- Consumes: `add_usage`, `merge_daily`, `project_label`.
- Produces: `CODEX_SESSIONS_DIR = Path.home()/".codex"/"sessions"`; `read_codex_file(path) -> dict` (that file's daily buckets; raises `SourceFormatError` if no recognizable usage events and the file isn't empty); `scan_codex(source_state: dict, sessions_dir=CODEX_SESSIONS_DIR) -> dict` (mutates `source_state["files"][path] = {"size", "mtime", "daily"}`, re-reading a file only when size/mtime changed; keeps entries for deleted files; sets `source_state["error"]` to a message or None); `codex_daily(source_state) -> dict`; `codex_total(source_state) -> int`. `SourceFormatError` lives in `usage_stats.py`.
- Rules: count `token_usage_record` payload `usage`, de-duplicated by `response_id`; if a file has none, use growth of `token_count` `info.total_token_usage` totals (skip repeats and `info: null`). Model from the latest `turn_context.model` before the record; project from `session_meta.cwd`/`turn_context.cwd`. Ignore an incomplete final line.

- [ ] **Step 1: Write failing tests** with small JSONL fixtures written in `tmp_path`: `test_records_are_normalized` (input 12651 / cached 8960 / output 191 → input 3691, cache_read 8960, output 191), `test_duplicate_response_ids_count_once`, `test_running_total_fallback_skips_repeats` (totals 100, 100, 250 → 250), `test_partial_last_line_ignored`, `test_rescan_replaces_file_contribution`, `test_deleted_file_keeps_history`, `test_unrecognized_file_sets_error`.
- [ ] **Step 2: Run** `pytest tests/test_codex_source.py -q` → fail (module missing).
- [ ] **Step 3: Implement** `codex_source.py`.
- [ ] **Step 4: Run** tests → pass; then `python3 -c` scan of the real `~/.codex/sessions` prints a lifetime total equal to the sum of each file's final `total_tokens`.
- [ ] **Step 5: Commit** `Read Codex usage from its session logs`.

### Task 3: opencode reader

**Files:**
- Create: `opencode_source.py`
- Test: `tests/test_opencode_source.py`

**Interfaces:**
- Consumes: `add_usage`, `merge_max_daily`, `project_label`, `SourceFormatError`.
- Produces: `OPENCODE_DB = Path.home()/".local"/"share"/"opencode"/"opencode.db"`; `read_opencode(db_path) -> dict` (daily buckets incl. `recorded_cost` from message `cost`); `scan_opencode(source_state, db_path=OPENCODE_DB) -> dict` (`source_state["daily"] = merge_max_daily(saved, current)`; on `sqlite3.Error`/missing columns sets `source_state["error"]` and keeps saved); `opencode_daily(source_state)`, `opencode_total(source_state) -> int`.
- Query: `session_message` joined to `session_v2` on `session_id = session_v2.id` for `directory`; only rows whose `data` has `tokens`; day from `time.created` (ms, local date).

- [ ] **Step 1: Write failing tests** building a temp SQLite with the two tables: `test_tokens_normalized_and_cost_recorded`, `test_project_from_session_directory`, `test_scan_never_shrinks_after_deletion`, `test_missing_table_sets_error_keeps_history`, `test_opened_read_only` (db file mtime unchanged after scan).
- [ ] **Step 2: Run** → fail.
- [ ] **Step 3: Implement** `opencode_source.py`.
- [ ] **Step 4: Run** → pass; real-db smoke scan prints 30-message-range totals without error.
- [ ] **Step 5: Commit** `Read opencode usage from its database`.

### Task 4: Tool registry, views and recorded cost

**Files:**
- Create: `tools.py`
- Modify: `pricing.py`
- Test: `tests/test_tools.py`, `tests/test_pricing.py`

**Interfaces:**
- Produces: `TOOLS = [("claude_code", "Claude Code"), ("codex", "Codex"), ("opencode", "opencode")]`; `detect_tools(claude_dir, codex_dir, opencode_db) -> list[str]` (defaults to real paths); `scan_tools(state, enabled: list[str]) -> None` (Claude via existing `refresh_grand_total`; others into `state.setdefault("sources", {})[key]`); `tool_view(state, key) -> dict` with keys `key, name, daily, grand_total, error`; `combined_view(state, enabled) -> dict` (same keys, `key="all"`, name "All tools", `grand_total` = sum of the tools' totals). `estimate_cost(models, recorded=None)` — models present in `recorded` use that dollar amount and aren't counted as unpriced.

- [ ] **Step 1: Write failing tests** `test_detect_only_existing`, `test_claude_view_uses_existing_keys` (no copy into `sources`), `test_combined_sums_tools_and_groups_by_model`, `test_scan_skips_disabled_tools`, `test_estimate_cost_uses_recorded_cost`.
- [ ] **Step 2: Run** → fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** full suite → pass.
- [ ] **Step 5: Commit** `Add tool registry with per-tool and combined views`.

### Task 5: Panel content for tools, Settings and welcome

**Files:**
- Modify: `stats_tabs.py`
- Test: `tests/test_stats_tabs.py`

**Interfaces:**
- Consumes: view dict from Task 4, `recorded_cost_in_range`.
- Produces: `build_panel(view, sessions, friends, show_leaderboard: bool, today=None) -> list[tab]` (`_Data` built from `view["daily"]`/`view["grand_total"]`; Overview adds row `("row", "New input + output", ...)` and, if `view["error"]`, a first card `("note", f"{name} data couldn't be read: {error}")`); `settings_tab(state, paused, interval_choices, detected: list[str])` gains card "AI tools": one `("switch", name, key in enabled, f"tool:{key}")` per detected tool, then `("switch", "Combine all tools", state["combine_tools"], "combine_tools")`; `welcome_tab(detected, chosen: list[str]) -> tab` (key "welcome", title "Welcome", switches `f"welcome_tool:{key}"`, note when none detected, buttons `[("Continue", "arrow.right.circle", "welcome_done")]`); `tool_choices(state, detected) -> list[(key, name)]` for the switcher (enabled ∩ detected-or-has-history).

- [ ] **Step 1: Update/add failing tests**: existing build_panel tests pass a view; `test_overview_shows_new_input_plus_output`, `test_error_note_shown`, `test_settings_lists_detected_tools_only`, `test_welcome_with_no_tools_detected`, `test_leaderboard_only_when_requested`.
- [ ] **Step 2: Run** → fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → pass.
- [ ] **Step 5: Commit** `Show tool views, tool settings and a welcome picker`.

### Task 6: Sessions for Codex and opencode

**Files:**
- Modify: `active_sessions.py`
- Test: `tests/test_active_sessions.py`

**Interfaces:**
- Produces: `pids_named(ps_output, name) -> list[str]` (generalizes `claude_pids`, which stays as a wrapper); `running_tool_sessions(name) -> list[{"label": str, "tokens": None}]` (cwd per running process, labels via `display_name`). `_sessions_tab` shows `"running"` when tokens is None.

- [ ] **Step 1: Failing tests** `test_pids_named_matches_full_paths` (codex/opencode full paths), `test_sessions_tab_running_without_tokens`.
- [ ] **Step 2–4:** run → implement → pass.
- [ ] **Step 5: Commit** `List running Codex and opencode sessions`.

### Task 7: App and panel wiring

**Files:**
- Modify: `app.py`, `panel_view.py`, `README.md`
- Test: `tests/test_app_state.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `init_tool_state(state, fresh_install: bool) -> None` in `app.py` (pure; sets `enabled_tools`, `combine_tools`, `selected_tool`, `onboarding_done` only if missing); panel `render(tabs, settings, footer, paused, tool_choices=None, selected_tool=None, welcome=None)`: a segmented tool switcher under the header when `tool_choices` has 2+ entries (action `select_tool`); when `welcome` is given the panel shows only it. App: scans enabled tools in `refresh`; menu bar number from the selected tool (or combined); fresh install opens the panel on the welcome view at start; Leaderboard tab only in the Claude Code view.

- [ ] **Step 1: Failing tests** `test_existing_install_keeps_preferences` (copy of a real-shaped state dict: every original key/value unchanged, `enabled_tools == ["claude_code"]`, `onboarding_done is True`), `test_fresh_install_starts_with_no_tools`.
- [ ] **Step 2: Run** → fail.
- [ ] **Step 3: Implement** wiring, switcher, welcome, README "Is this safe" + tabs text listing exactly what Codex/opencode data is read.
- [ ] **Step 4: Verify:** full suite passes; offscreen render of Claude Code, Codex, combined and welcome views look right; live scratch copy on a copy of `state.json` opens, switches tools, and the real `state.json` preference values are unchanged after the real app restarts.
- [ ] **Step 5: Commit** `Add tool switcher, welcome picker and tool settings`; push; restart app.
