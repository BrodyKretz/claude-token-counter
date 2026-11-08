# Future additions

Ideas we've decided to hold off on, with why and what we already know, so
picking one up later doesn't start from zero.

## Cursor usage tracking

**Status:** deferred (2026-11-07).

**Why it's on hold:** Cursor doesn't store token counts on your Mac (its
local databases had no usable usage data), so tracking it means asking
Cursor's servers. Cursor has no official way for an individual to read their
own usage: its official usage reporting is the Admin API, which is for team
admins only. The only route for individuals is the private connection the
cursor.com dashboard uses, which is undocumented and could change or break
without notice.

**Revisit when:** Cursor publishes an official, documented usage API for
individual accounts (or the user is on a Cursor team and wants the Admin API).

**Proposed design, if we build it:**

- **Opt-in.** Off until turned on in Settings, like the Leaderboard.
- **Private sign-in.** The app opens cursor.com in the browser and the user
  signs in there; the app never sees the password, only the session key
  Cursor issues.
- **Key storage.** The key lives only in the macOS Keychain (the same place
  the Leaderboard's GitHub token goes). Never written to `state.json`, logs,
  or the repo, and never sent anywhere except cursor.com over HTTPS.
- **Nothing new leaves the Mac.** The app fetches the user's own usage and
  keeps it locally. Cursor numbers stay out of the Leaderboard unless the
  user opts in.
- **Sign Out** deletes the key from the Keychain.
- **Failure is contained.** If Cursor changes its private connection, only
  Cursor tracking stops; the rest of the app keeps working, and the panel
  says Cursor data is unavailable instead of showing wrong numbers.

**Open questions:**

- Could the app reuse the sign-in the Cursor app already has on the Mac,
  instead of a second sign-in? Not checked: reading another app's stored
  credentials is sensitive, and we'd want the user's explicit go-ahead
  before even looking.
- How does Cursor count tokens (cached input, reasoning), and does it line
  up with how the other tools are counted?
- Does Cursor's terms of service allow reading the dashboard's private
  connection from a third-party app?
