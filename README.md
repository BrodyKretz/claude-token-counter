# Claude Token Counter

A tiny macOS menu bar app that shows how many Claude Code tokens you've used, in total, forever. It just sits in your menu bar and the number keeps going up.

![menu bar](https://img.shields.io/badge/platform-macOS-lightgrey)

## Is this safe to run?

Yes. There's no compiled binary and nothing hidden -- it's a handful of short Python files and 2 shell scripts, all listed below, all readable in a few minutes.

By default it never connects to the internet or sends your data anywhere. The only things it touches are:

- Log files already on your own Mac (`~/.claude/projects/`, which Claude Code itself writes)
- `launchctl`, macOS's own built-in tool, only to turn its "start at login" setting on or off

**The one exception is the Leaderboard (Beta) feature, and it's entirely opt-in** -- nothing below happens unless you click "Get Set Up with Leaderboard" yourself. See the [Leaderboard (Beta)](#leaderboard-beta) section for exactly what that does.

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
- **Today's tokens used** -- just what you've used since midnight
- **Tracking since** -- the date you first installed this
- **Leaderboard (Beta)** -- see below, this one's still a work in progress
- **Active Sessions** -- every Claude Code terminal you currently have open, and how many tokens each one has used
- **Pause/Resume Scanning**, plus a **Scans every _N_ seconds** menu to change how often it checks for new usage
- **Start at Login** -- turn auto-start on or off
- **Quit**

### Leaderboard (Beta)

This is a genuine work in progress, not a finished feature -- treat it as rougher and less battle-tested than everything else in this app. It's also completely opt-in: until you click "Get Set Up with Leaderboard," none of what follows happens, and the rest of the app (token counting, Active Sessions, etc.) works exactly the same with or without it.

Here is exactly what it does, in order, when you click "Get Set Up with Leaderboard":

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
leaderboard.py               Leaderboard (Beta) -- local friends-list storage and sorting
gist_sync.py                 Leaderboard (Beta) -- Keychain token storage + GitHub Gist API calls
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
