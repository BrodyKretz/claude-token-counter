# Claude Token Counter

A tiny macOS menu bar app that shows your lifetime Claude Code token usage, and keeps counting from wherever it's at.

![menu bar](https://img.shields.io/badge/platform-macOS-lightgrey)

## What it does

- Reads Claude Code's own session logs (`~/.claude/projects/**/*.jsonl`) and sums up every token you've used (input + output + cache creation + cache read).
- Keeps a running grand total in a local `state.json`, tracked by file byte-offset so it only ever counts new tokens once -- even after Claude Code prunes old session logs (it deletes them after ~30 days), the total keeps climbing instead of shrinking.
- Refreshes every 15 seconds while running.
- Shows a live per-terminal breakdown ("Active Sessions") of every currently-running `claude` process and how many tokens its session has used.
- Everything is local. The only things it talks to are files on your own disk and `launchctl` (for the login-item toggle) -- no network calls, no telemetry.

## Requirements

- macOS
- Python 3.9+
- [`rumps`](https://github.com/jaredks/rumps) (installed automatically by `install.sh`, or `pip install -r requirements.txt`)

## Install

```bash
git clone https://github.com/<your-username>/claude-token-counter.git
cd claude-token-counter
./install.sh
```

This installs a LaunchAgent that starts the app now and automatically at every login. Look for the 🪙 icon in your menu bar.

## Menu

Click the menu bar icon for:

- **Claude tokens used** -- the exact running total
- **Tracking since** -- the date this install first computed a baseline
- **Active Sessions** -- one entry per currently-running Claude Code terminal, with its own token count
- **Pause/Resume Scanning** -- temporarily stop the 15s refresh loop
- **Start at Login** -- toggle whether it auto-starts next time you log in
- **Quit**

## Uninstall

```bash
./uninstall.sh
```

Removes the LaunchAgent. `state.json` (your accumulated total) is left alone in case you reinstall later -- delete it yourself for a clean slate.

## Running tests

```bash
pip install pytest
pytest
```

## How "active sessions" matching works

Claude Code doesn't expose which exact session file belongs to which running process, so the app makes a best-effort match: for each running `claude` process, it looks at the process's working directory and picks the most-recently-modified session file in that directory's log folder. If you have several terminals open in the exact same directory at once, each gets matched to one of the most recent files there, but which exact terminal maps to which file isn't guaranteed.

## License

MIT -- see [LICENSE](LICENSE).
