# Multi-tool tracking (Codex, opencode) — design

## Intent

Claude Tracker counts only Claude Code today. The user also uses other AI
coding tools and wants their usage in the same app: each tool on its own by
default, with a setting to see every model's usage across all tools at once.

## Goals

- Track **Claude Code, Codex and opencode** from the data each keeps on the Mac.
- **Default view: one tool at a time.** A tool switcher picks which tool the
  panel (and the menu bar number) shows.
- **Setting: combined view.** Every tool's usage together, grouped by model.
- **First run asks which tools you use** and enables only those. Changeable
  later in Settings.
- **Existing installs keep their settings.** No preference the user already
  set is changed; existing installs start with Claude Code enabled only, and
  no first-run prompt.

## Non-goals

- Cursor (deferred: no local data and no official personal usage API; see
  `future-additions.md`).
- Sharing other tools' numbers on the Leaderboard (stays Claude Code only).
- Renaming the app (user's call; left as "Claude Tracker" for now).

## Anti-goals

- Wrong numbers presented as right: double counting, or silently stale data
  after a tool changes its format.
- Reading anything beyond token counts, model, time and project folder
  (Codex logs contain prompts and code; opencode's database has credential
  and account tables).

## Data sources (verified on the user's Mac)

| Tool | Where | What it has |
|---|---|---|
| Claude Code | `~/.claude/projects/**/*.jsonl` | Already supported. |
| Codex | `~/.codex/sessions/**/rollout-*.jsonl` | `token_usage_record` per model response (unique `response_id`; their sum equals the session's final running total), `token_count` running totals, `session_meta`/`turn_context` with `cwd` and `model`. |
| opencode | `~/.local/share/opencode/opencode.db` (SQLite, WAL) | `session_message.data` JSON with `tokens` {input, output, reasoning, cache.read, cache.write}, `model.id`, `cost`, `time.created` (ms); `session_v2.directory` per session. |

## Decisions

1. **One token vocabulary.** Every source is normalized to the existing
   categories: input (new), output, cache_write_5m/1h, cache_read.
   - Codex `input_tokens` includes cached tokens: input = input − cached,
     cache_read = cached, cache_write_5m = cache_write_input_tokens,
     output = output_tokens (already includes reasoning).
   - opencode: input, output + reasoning, cache read/write as given.
   - Totals keep meaning "everything the model processed" (unchanged for
     Claude). Each tool's Overview also shows **new input + output**, the
     fair cross-tool comparison.
2. **No double counting.**
   - Codex: count `token_usage_record` entries, de-duplicated by
     `response_id` within a file. Files with no such records fall back to the
     growth of the `token_count` running total, ignoring repeats.
   - Rewritten/migrated files can't double count: a Codex file is re-read
     whole when its size or modified time changes, and its contribution
     **replaces** the previous one. Files that disappear keep their last
     contribution (lifetime totals survive pruning).
   - opencode: aggregate per day + model from the database; merge into saved
     buckets taking the **larger** of saved vs current, so deleted sessions
     don't shrink history.
3. **Robustness.** Each reader validates the shape it expects. On failure the
   tool's page says its data couldn't be read; other tools keep working.
   opencode is opened read-only and only `session_message` / `session_v2`
   are queried. Tests use real-shaped samples.
4. **Storage.** Claude Code's existing state keys stay exactly where they are
   (no migration of the user's data). New tools live under
   `state["sources"][tool]`.
5. **Cost.** Price by model prefix (Claude table as today). opencode uses its
   own recorded cost. Codex models (`gpt-5.6-*`) show as "not priced" until
   prices are added.
6. **Claude-specific features.**
   - Menu bar shows the selected tool's number (combined total in combined
     view). The existing display/size preferences apply as-is.
   - Sessions tab: Claude Code as today; Codex and opencode list running
     processes by folder (no per-session token counts).
   - Leaderboard: Claude Code only; its tab appears only in the Claude Code view.
7. **Same model via different tools.** Each response is counted once, under
   the tool that made it. The combined view groups by model across tools.
8. **History.** Backfilled from whatever each tool still has on disk.
9. **Detection.** A tool is offered only if its data exists. Settings lists
   detected tools with on/off switches, plus "Combine all tools".
10. **First run.** On a fresh install (no `state.json`) the panel opens on a
    welcome view: "Which AI tools do you use?" with a switch per detected
    tool (all off), and Continue. Nothing is tracked until chosen.

## Approaches considered

- **Per-tool state alongside Claude's (chosen).** Leaves Claude data
  untouched; each tool owns its reader and storage; views take a tool's
  per-day buckets. Simple migration (none) and contained failures.
- **One merged per-day store with a tool field.** Cleaner queries, but
  requires migrating the user's existing Claude data; rejected given
  "don't change my preferences/data".
- **Recompute everything from disk each scan (no stored totals).** Simplest
  code, but loses lifetime totals when tools prune logs; rejected.

## Left to the builder

Exact UI placement and styling of the tool switcher and welcome view,
within the panel's existing look; process names to detect for Sessions.
