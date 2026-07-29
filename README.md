# Claude Token Counter

A tiny macOS menu bar app that shows how many Claude Code tokens you've used, in total, forever. It just sits in your menu bar and the number keeps going up.

![menu bar](https://img.shields.io/badge/platform-macOS-lightgrey)

## Is this safe to run?

Yes. There's no compiled binary and nothing hidden -- it's 4 short Python files and 2 shell scripts, all listed below, all readable in a few minutes. It never connects to the internet or sends your data anywhere. The only things it touches are:

- Log files already on your own Mac (`~/.claude/projects/`, which Claude Code itself writes)
- `launchctl`, macOS's own built-in tool, only to turn its "start at login" setting on or off

## Quick start

1. Open Terminal and paste this in, one line at a time:
   ```bash
   git clone https://github.com/BrodyKretz/claude-token-counter.git
   cd claude-token-counter
   ./install.sh
   ```
2. Look at your menu bar (top right of your screen). You'll see a 🪙 icon with a number next to it.

That's it. It now also starts automatically every time you log in.

If step 1 fails because `rumps` isn't installed, the script installs it for you automatically the first time (it needs Python 3 and `pip`, which come standard on macOS).

## What you'll see when you click the icon

- **Claude tokens used** -- your exact running total
- **Tracking since** -- the date you first installed this
- **Active Sessions** -- every Claude Code terminal you currently have open, and how many tokens each one has used
- **Pause/Resume Scanning** -- temporarily stop it from checking for new usage
- **Start at Login** -- turn auto-start on or off
- **Quit**

## Uninstalling

```bash
./uninstall.sh
```

This removes it completely from starting at login. Your accumulated total (`state.json`) is left on disk in case you reinstall later -- delete that file yourself if you want to reset to zero.

## How it works

- Claude Code already writes a log of every message you send and receive to `~/.claude/projects/**/*.jsonl` on your own machine.
- This app reads those logs and adds up the tokens (input + output + cache) used in every message.
- It remembers exactly how far into each log file it has already counted, so re-checking every 15 seconds only adds *new* tokens, never double-counts, and the total keeps climbing correctly even after Claude Code deletes old logs (it prunes anything older than ~30 days).

**A note on "Active Sessions" accuracy:** Claude Code doesn't expose which exact log file belongs to which open terminal, so this is a best-effort match based on which directory each terminal is running in and which log file in that directory was written to most recently. If you have two terminals open in the exact same folder at once, they may get matched to the wrong one of each other -- everything else is unaffected.

## Project layout

```
app.py                       menu bar UI (rumps) -- also handles the "start at login" toggle
token_math.py                reads the jsonl logs and does the token accounting
active_sessions.py           matches running `claude` processes to their sessions
install.sh / uninstall.sh    set up / remove the LaunchAgent
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
