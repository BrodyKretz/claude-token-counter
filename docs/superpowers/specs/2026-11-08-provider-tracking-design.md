# Provider tracking (OpenAI, DeepSeek, Kimi): design

## Intent

Let the user track usage by AI *provider* (the company whose model ran), next
to the existing per-tool views. They asked for OpenAI, DeepSeek and Kimi as
options that can be turned on when wanted. Accuracy is the priority; an API
key must not be needed when local data is already accurate.

## Goals

- OpenAI, DeepSeek and Kimi are options in Settings, off by default. Each
  enabled one appears in the "Tracking" dropdown.
- **Local (no key):** a provider view shows that provider's models used
  through Claude Code, Codex and opencode on this Mac. The token counts are
  the tools' own exact counts, filtered by model.
- **Account (optional key):** an API key adds account-wide numbers from the
  provider's own API, shown in a separate card that is never added to the
  local totals (they overlap):
  - OpenAI admin key (`sk-admin-…`): daily tokens per model
    (`/v1/organization/usage/completions`) and billed cost
    (`/v1/organization/costs`), last 30 days.
  - Kimi admin key (`sk-admin-…`, `billing:read`): daily tokens per model
    (`/v1/admin/organizations/usage/completions`), plus balance and total
    spent (`/v1/admin/organizations/account`, milli-cents).
  - Kimi ordinary API key: balance only (`/v1/users/me/balance`).
  - DeepSeek API key: balance only (`/user/balance`). DeepSeek publishes no
    usage-history API.

## Non-goals and anti-goals

- No change to existing preferences or to "Combine all tools" (it sums tools,
  so adding provider views would double count).
- No invented prices for non-Claude models: unpriced tokens stay labelled as
  unpriced; real billed cost comes only from the account APIs.
- Keys never touch state.json, logs, argv or the repo.

## Decisions

- **Which provider a model belongs to** is decided from the model name
  (`gpt-*`, `o1`/`o3`/`o4…`, `codex-*`, `chatgpt-*` = OpenAI; contains
  `deepseek` = DeepSeek; contains `kimi`/`moonshot` = Kimi), with an
  optional `vendor/` prefix (`openai/`, `deepseek/`, `moonshotai/`). A model
  counts under its maker wherever it ran (e.g. DeepSeek via OpenRouter).
- **Projects in a provider view:** buckets now also record
  `model_projects` ({model: {project: tokens}}). Older buckets without it
  are attributed only when every model in that day's bucket belongs to the
  provider; otherwise those days' projects are left out rather than guessed.
- **Data coverage:** while any provider is enabled, every tool detected on
  the Mac is scanned (read-only), so e.g. Codex counts toward OpenAI even if
  the Codex view itself is off.
- **Keys** live in the macOS Keychain (service
  `com.raymondtian.claudetracker.apikey`, account = provider). They are
  written through `security -i` on stdin so they never appear in a process
  list, sent only over HTTPS to that provider's own API host, and removed
  with "Remove key". state.json only records *that* a key exists.
- **Fetching** runs on a background thread at most every 15 minutes (and
  right after a key is added); results and errors are stored per provider
  under `state["accounts"]`, keeping the last good numbers on failure.
- **Kimi region:** `api.moonshot.ai` first; on 401 retry `api.moonshot.cn`
  (both Moonshot's own hosts), remembering which worked.
- **Menu bar icon:** the provider's installed app icon (OpenAI reuses the
  ChatGPT/Codex sources); otherwise a drawn monogram (`DS`, `K`), never the
  coin, so views stay distinguishable.
- Live Sessions tab is hidden in provider views: a running tool session
  can't be tied to one provider.
