# Claude Tracker

A tiny macOS menu bar app (no Dock icon) that shows how many Claude Code tokens you've used, in total, forever. It just sits in your menu bar and the number keeps going up.

![menu bar](https://img.shields.io/badge/platform-macOS-lightgrey)

## Is this safe to run?

Yes. There's no compiled binary and nothing hidden -- it's a handful of short Python files and 2 shell scripts, all listed below, all readable in a few minutes.

By default it never connects to the internet or sends your data anywhere. The only things it touches are:

- Usage data your AI coding tools already keep on your own Mac, only for the tools you turn on:
  - **Claude Code:** its logs in `~/.claude/projects/`
  - **Codex:** its session logs in `~/.codex/sessions/`
  - **opencode:** its database at `~/.local/share/opencode/opencode.db`, opened read-only

  From these it reads only token counts, which model was used, when, and which project folder. It skips your prompts, code and replies, and never touches opencode's account or credential tables.
- `launchctl`, macOS's own built-in tool, only to turn its "start at login" setting on or off

**There are two exceptions, both opt-in:** an API key you add for an AI provider (see [OpenAI, DeepSeek and Kimi](#openai-deepseek-and-kimi)), and the Leaderboard (Beta) feature.

**The Leaderboard (Beta) is entirely opt-in** -- its tab is hidden until you turn on **Show Leaderboard (Beta)** in Settings, and nothing below happens unless you then click "Set Up Leaderboard" yourself. See the [Leaderboard (Beta)](#leaderboard-beta) section for exactly what that does.

## Quick start

1. Open Terminal and paste this in, one line at a time:
   ```bash
   git clone https://github.com/raymondtian30/claude-tracker.git
   cd claude-tracker
   ./install.sh
   ```
2. Look at your menu bar (top right of your screen). You'll see a 🪙 icon with a number next to it.

That's it. It now also starts automatically every time you log in, and **Claude Tracker** is in your Applications folder (Finder, Launchpad and Spotlight) if you ever quit it and want it back. Opening it while it's already running just opens its panel.

The app in Applications is a small launcher that runs the code in this folder, so your totals stay in `state.json` here and a `git pull` updates the app. If you move this folder, run `./install.sh` again.

If step 1 fails because `rumps` isn't installed, the script installs it for you automatically the first time (it needs Python 3 and `pip`, which come standard on macOS).

## What you'll see when you click the icon

The first time you open it, it asks which AI tools you use (Claude Code, Codex, opencode -- only the ones found on your Mac are listed) and tracks only those. If you track more than one, a dropdown at the top picks which tool you're looking at, and the menu bar shows that tool's icon (taken from its app or editor extension already on your Mac; the coin if none is found, and in the combined view); turn on **Combine all tools** in Settings to see every tool's usage together, grouped by model.

A panel opens with a row of tabs along the top. Click an icon to switch tabs:

- **Overview** -- today's and lifetime totals, a chart of the last 14 days, and yesterday / last 7 days / this month / your biggest day
- **Token Types** -- today's and lifetime tokens split into input, output, cache write and cache read, each with a bar showing its share
- **Models** -- today's and lifetime tokens per model (Opus, Sonnet, Haiku...)
- **Projects** -- the 3 folders you used the most tokens in over the last 7 days
- **Estimated API Cost** -- what your usage would cost at Anthropic's pay-as-you-go API prices. Just for fun: a Pro or Max subscription is flat-rate, so you aren't billed this. Prices live in `pricing.py` and will drift over time.
- **Active Sessions** -- every Claude Code terminal you currently have open, and how many tokens each one has used
- **Leaderboard (Beta)** -- hidden unless you turn it on in Settings; see below, this one's still a work in progress

At the bottom: the date you started tracking, a **Settings** button (which AIs to track -- coding tools and providers -- with optional provider API keys, and whether to combine tools; what the menu bar shows -- lifetime total, today's total, or just the icon -- and its text size; how often to scan; pause scanning; start at login; show the Leaderboard; version and credits) and **Quit**. Click anywhere outside the panel to close it.

### OpenAI, DeepSeek and Kimi

Turn on OpenAI, DeepSeek or Kimi under **AI tools** in Settings (listed after your coding tools) (all off by default) and each appears in the **Tracking** dropdown. A provider view counts that company's models wherever they ran -- Claude Code, Codex or opencode -- using the tools' own exact token counts, so **no sign-in or key is needed**. The model name decides the company (`gpt-*`, `o3`, `codex-*` → OpenAI; `deepseek-*` → DeepSeek; `kimi-*`, `moonshot-*` → Kimi), so e.g. Kimi via OpenRouter still counts as Kimi. While any provider is on, every tool found on your Mac is read (read-only), so Codex counts toward OpenAI even if the Codex view is off. "Combine all tools" doesn't add provider views on top, so nothing is counted twice. Live Sessions isn't shown for providers, since a running session can't be tied to one company.

**Optional API key, for usage from outside this Mac.** Each provider view has an account card. Add a key in Settings and it shows what that provider's own API reports:

| Provider | Key | Shows |
|---|---|---|
| OpenAI | admin key (`sk-admin-…`, from Settings → Admin keys) | daily tokens per model and billed cost, last 30 days |
| Kimi | admin key (`sk-admin-…`, `billing:read`) | daily tokens per model, balance, total spent |
| Kimi | ordinary API key | balance |
| DeepSeek | API key | balance (DeepSeek has no usage-history API) |

These account numbers are shown in their own card and never added to the local totals, since the two overlap. Numbers refresh every 15 minutes; if a refresh fails, the last good numbers stay with the error shown under them.

**How keys are kept private:** a key is stored only in your **macOS Keychain**, written through `security -i` on standard input so it never appears in a process list. It's never written to `state.json`, any log or this repo. It's sent only over HTTPS, only to that provider's own API (`api.openai.com`, `api.deepseek.com`, or `api.moonshot.ai` / `api.moonshot.cn`), and redirects aren't followed. **Remove Key** deletes it from the Keychain. Only usage numbers and balances are requested.

### Leaderboard (Beta)

This is a genuine work in progress, not a finished feature -- treat it as rougher and less battle-tested than everything else in this app. It's also completely opt-in: its tab only appears after you turn on **Show Leaderboard (Beta)** in Settings, and until you click "Set Up Leaderboard," none of what follows happens, and the rest of the app (token counting, Active Sessions, etc.) works exactly the same with or without it.

Here is exactly what it does, in order, when you click "Set Up Leaderboard":

1. **It opens your browser** to a GitHub page that creates a Personal Access Token scoped *only* to the `gist` permission (nothing else on your GitHub account -- it cannot read your repos, emails, or anything beyond gists). You generate the token yourself on GitHub's own site.
2. **You paste that token into a prompt in the app.** The token is stored in your **macOS Keychain** (the same secure system macOS itself uses for saved passwords) -- never written to any file in this project, never logged, never leaves your Mac except as an authorization header sent directly to `api.github.com` over HTTPS.
3. **It creates one secret Gist on your own GitHub account** -- a single small JSON file containing only: the display name you typed in, your total token count, your token count from yesterday, and today's date. That's the entire payload. No logs, no message content, no file paths, no code ever leaves your machine.
4. **Once a day** (checked whenever the app does its normal scan, gated by date so it only actually runs once), it pushes your updated numbers to that same Gist, and separately fetches the Gist of every friend you've added, updating your local `friends.json`. You can also trigger both manually any time with "Push Update Now" / "Pull Latest Now."

**Adding a friend** ("Add Friend by Code") just means pasting in the ID of their Gist -- that ID is their "friend code." Reading a friend's Gist is a plain, unauthenticated read of a known URL; no token or permission exchange happens between you and them.

**Where things live locally:** your GitHub token is Keychain-only. Your Gist ID and display name are in `state.json`. Your friends' cached scores are in `friends.json`. All three are gitignored -- none of this is ever part of the git history of this project, and none of it is sent to any server other than `api.github.com`, which GitHub itself runs.

**Honest caveat:** since every person's own client reports its own numbers, there's no way for anyone to verify a score is real. This is an honor-system leaderboard for fun among friends, not a tamper-proof one -- which is exactly what the disclaimer inside the menu itself says.

## Uninstalling

```bash
./uninstall.sh
```

This removes it from starting at login and deletes **Claude Tracker** from your Applications folder. Your accumulated total (`state.json`) is left on disk in case you reinstall later -- delete that file yourself if you want to reset to zero.

## How it works

- Claude Code already writes a log of every message you send and receive to `~/.claude/projects/**/*.jsonl` on your own machine.
- Codex and opencode count tokens a bit differently (for example, Codex includes cached tokens in its input number). The app converts each into the same four types -- new input, output, cache write, cache read -- so the tools add up and compare consistently. Each tool's Overview also shows **new input + output**, which compares tools fairly since cache reads can dominate a total.
- This app reads those logs and adds up the tokens (input + output + cache) used in every message.
- It also files each message into a per-day bucket (by model, token type and project), which powers the breakdown, history and cost menus. The first time you run a version with these menus, it fills the buckets from the logs still on disk; anything Claude Code already pruned shows up as "older, no detail".
- It remembers exactly how far into each log file it has already counted, so re-checking every 15 seconds only adds *new* tokens, never double-counts, and the total keeps climbing correctly even after Claude Code deletes old logs (it prunes anything older than ~30 days).

**A note on "Sessions" tab accuracy:** Claude Code doesn't expose which exact log file belongs to which open terminal, so this is a best-effort match based on which directory each terminal is running in and which log file in that directory was written to most recently. If you have two terminals open in the exact same folder at once, they may get matched to the wrong one of each other -- everything else is unaffected.

## Version and credits

Current version: **2.1.0**, following [Semantic Versioning](https://semver.org) (MAJOR.MINOR.PATCH). The version lives in `version.py` and is shown in Settings.

- Original app by [BrodyKretz](https://github.com/BrodyKretz/claude-token-counter)
- Redesign and new features (panel, stats tabs, cost estimate, fixes) by Raymond Tian ([raymondtian30](https://github.com/raymondtian30/claude-tracker))

## Project layout

```
app.py                       menu bar app (rumps): scanning, settings, leaderboard actions
token_math.py                reads the jsonl logs and does the token accounting
usage_stats.py               per-day buckets and the breakdown / model / project / history views
codex_source.py              reads Codex usage from its session logs
opencode_source.py           reads opencode usage from its database (read-only)
tools.py                     the supported tools, detection, scanning, per-tool and combined views
providers.py                 OpenAI / DeepSeek / Kimi: which models are theirs, provider views
accounts.py                  optional provider API keys (Keychain) and account usage/balance fetching
tool_icons.py                finds each tool's or provider's icon on this Mac for the menu bar (or draws a monogram)
stats_tabs.py                what each panel tab shows, as plain data
panel_view.py                draws the panel (tabs, cards, bars, chart, settings) with AppKit
pricing.py                   API price table and the estimated-cost math
version.py                   app name, version number and credits
active_sessions.py           matches running `claude` processes to their sessions
leaderboard.py               Leaderboard (Beta) -- local friends-list storage and sorting
gist_sync.py                 Leaderboard (Beta) -- Keychain token storage + GitHub Gist API calls
build_app.py                 builds "Claude Tracker.app" (launcher, Info.plist, icon) for Applications
single_instance.py           keeps one copy running; opening it again shows the running copy's panel
install.sh / uninstall.sh    build the app and set up start-at-login / remove both
tests/                       pytest suite for the logic in the modules above
```

## Requirements

- macOS
- Python 3.9+

## Running the tests

```bash
pip install pytest
pytest
```

## License

MIT -- see [LICENSE](LICENSE).
