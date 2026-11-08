import os
import subprocess
import urllib.error
import webbrowser
from datetime import date, timedelta
from pathlib import Path

import rumps
from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSAttributedString,
    NSFont,
    NSFontAttributeName,
)

from active_sessions import active_sessions
from gist_sync import (
    NEW_TOKEN_URL,
    create_gist,
    fetch_gist,
    get_github_token,
    set_github_token,
    update_gist,
)
from leaderboard import load_friends, save_friends, sorted_friends
from pricing import estimate_cost, format_dollars
from token_math import (
    backfill_daily,
    format_count,
    load_state,
    refresh_grand_total,
    save_state,
    sum_usage_for_today,
)
from usage_stats import (
    category_totals,
    history,
    model_totals,
    models_all_time,
    models_in_range,
    top_projects,
    total_in_range,
)

STATE_FILE = Path(__file__).resolve().parent / "state.json"
REFRESH_SECONDS = 15
SCAN_INTERVAL_CHOICES = [5, 15, 30, 60, 300]
LABEL = "com.claudetokencounter.menubar"

TITLE_MODES = [
    ("lifetime", "Lifetime Total"),
    ("today", "Today's Total"),
    ("icon", "Icon Only"),
]

CATEGORY_LABELS = [
    ("input", "Input"),
    ("output", "Output"),
    ("cache_write", "Cache write"),
    ("cache_read", "Cache read"),
]

MODEL_FAMILIES = ["fable", "mythos", "opus", "sonnet", "haiku"]


def _ordinal_suffix(day):
    if 11 <= day % 100 <= 13:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")


def _format_tracking_date(iso_date_str):
    parsed = date.fromisoformat(iso_date_str)
    return f"{parsed.strftime('%B')} {parsed.day}{_ordinal_suffix(parsed.day)}, {parsed.year}"


def _format_interval(seconds):
    if seconds < 60:
        unit = "second" if seconds == 1 else "seconds"
        return f"{seconds} {unit}"
    minutes = seconds // 60
    unit = "minute" if minutes == 1 else "minutes"
    return f"{minutes} {unit}"


def _bold_menu_item(title):
    """A plain, non-clickable menu item rendered in bold, for use as a header."""
    item = rumps.MenuItem(title)
    item._menuitem.setEnabled_(False)
    size = NSFont.menuFontOfSize_(0.0).pointSize()
    attributed = NSAttributedString.alloc().initWithString_attributes_(
        title, {NSFontAttributeName: NSFont.boldSystemFontOfSize_(size)}
    )
    item._menuitem.setAttributedTitle_(attributed)
    return item


def _info_item(title):
    """A plain, non-clickable menu row (shown greyed out like a label)."""
    item = rumps.MenuItem(title)
    item._menuitem.setEnabled_(False)
    return item


def _model_display_name(model_id):
    """'claude-opus-5-5' -> 'Opus 5.5', 'claude-haiku-4-5-20251001' -> 'Haiku 4.5'."""
    parts = model_id.split("-")
    if len(parts) < 2 or parts[0] != "claude" or parts[1] not in MODEL_FAMILIES:
        return model_id
    version = [p for p in parts[2:] if p.isdigit() and len(p) <= 2]
    name = parts[1].capitalize()
    return f"{name} {'.'.join(version)}" if version else name


def _merge_cache_writes(categories):
    merged = dict(categories)
    merged["cache_write"] = merged.pop("cache_write_5m", 0) + merged.pop(
        "cache_write_1h", 0
    )
    return merged


def _percent(part, whole):
    if not whole or not part:
        return "0%"
    share = part / whole * 100
    return "<1%" if share < 1 else f"{share:.0f}%"


def _service_target():
    return f"gui/{os.getuid()}/{LABEL}"


def set_start_at_login(enabled):
    """Enable/disable this LaunchAgent starting at login via launchctl overrides.

    Does not touch the currently running process -- only affects whether
    launchd starts it again on the next login.
    """
    action = "enable" if enabled else "disable"
    subprocess.run(
        ["launchctl", action, _service_target()],
        check=True,
        capture_output=True,
        text=True,
    )


class TokenCounterApp(rumps.App):
    def __init__(self):
        super().__init__("Claude Tokens", quit_button="Quit")
        self.state = load_state(STATE_FILE)
        self.state.setdefault("first_seen_at", None)
        self.state.setdefault("start_at_login", True)
        self.state.setdefault("scan_interval_seconds", REFRESH_SECONDS)
        self.state.setdefault("leaderboard_view", "total")
        self.state.setdefault("my_gist_id", None)
        self.state.setdefault("leaderboard_name", None)
        self.state.setdefault("last_leaderboard_sync_date", None)
        self.state.setdefault("title_mode", "lifetime")
        if self.state["first_seen_at"] is None:
            self.state["first_seen_at"] = date.today().isoformat()
        # Backfill must run before the first refresh: it re-reads each file
        # only up to the offsets saved by the previous run.
        backfill_daily(self.state)
        refresh_grand_total(self.state)
        save_state(self.state, STATE_FILE)

        self.header_item = _bold_menu_item("Token Tracker for Claude Code")
        self.total_item = rumps.MenuItem(self._total_label())
        self.today_item = rumps.MenuItem(self._today_label())
        self.since_item = rumps.MenuItem(self._since_label())
        self.breakdown_item = rumps.MenuItem("Token Breakdown")
        self.models_item = rumps.MenuItem("By Model")
        self.projects_item = rumps.MenuItem("Top Projects (Last 7 Days)")
        self.history_item = rumps.MenuItem("History")
        self.cost_item = rumps.MenuItem("Estimated API Cost")
        self.title_mode_item = rumps.MenuItem("Menu Bar Shows")
        for mode, label in TITLE_MODES:
            option = rumps.MenuItem(label, callback=self.set_title_mode)
            option.mode = mode
            option.state = mode == self.state["title_mode"]
            self.title_mode_item.add(option)
        self.leaderboard_item = rumps.MenuItem("Leaderboard (Beta)")
        self.sessions_item = rumps.MenuItem("Active Sessions")
        self.pause_item = rumps.MenuItem("Pause Scanning", callback=self.toggle_pause)
        self.interval_item = rumps.MenuItem(self._interval_label())
        for seconds in SCAN_INTERVAL_CHOICES:
            option = rumps.MenuItem(
                f"Every {_format_interval(seconds)}", callback=self.set_scan_interval
            )
            option.interval_seconds = seconds
            option.state = seconds == self.state["scan_interval_seconds"]
            self.interval_item.add(option)
        self.login_item = rumps.MenuItem(
            "Start at Login", callback=self.toggle_start_at_login
        )
        self.login_item.state = self.state["start_at_login"]

        self.menu = [
            self.header_item,
            None,
            self.total_item,
            self.today_item,
            self.since_item,
            None,
            self.breakdown_item,
            self.models_item,
            self.projects_item,
            self.history_item,
            self.cost_item,
            None,
            self.leaderboard_item,
            self.sessions_item,
            None,
            self.title_mode_item,
            self.pause_item,
            self.interval_item,
            self.login_item,
        ]
        self._update_sessions_menu()
        self._rebuild_leaderboard_menu()
        self._rebuild_stats_menus()
        self._update_title()

        self.timer = rumps.Timer(self.refresh, self.state["scan_interval_seconds"])
        self.timer.start()

    def _total_label(self):
        return f"Claude tokens used: {self.state['grand_total']:,}"

    def _today_tokens(self):
        today = date.today()
        return total_in_range(self.state["daily"], today, today)

    def _today_label(self):
        return f"Today's tokens used: {self._today_tokens():,}"

    def _update_title(self):
        mode = self.state["title_mode"]
        if mode == "today":
            self.title = f"🪙 {format_count(self._today_tokens())}"
        elif mode == "icon":
            self.title = "🪙"
        else:
            self.title = f"🪙 {format_count(self.state['grand_total'])}"

    def set_title_mode(self, sender):
        for option in self.title_mode_item.values():
            option.state = option.mode == sender.mode
        self.state["title_mode"] = sender.mode
        save_state(self.state, STATE_FILE)
        self._update_title()

    @staticmethod
    def _reset_submenu(item):
        if item:
            item.clear()

    def _rebuild_stats_menus(self):
        daily = self.state["daily"]
        today = date.today()
        week_start = today - timedelta(days=6)
        today_models = models_in_range(daily, today, today)
        week_models = models_in_range(daily, week_start, today)
        month_models = models_in_range(daily, today.replace(day=1), today)
        lifetime_models = models_all_time(daily)
        lifetime_detailed = sum(t for _, t in model_totals(lifetime_models))
        earlier = max(self.state["grand_total"] - lifetime_detailed, 0)

        # Token Breakdown
        self._reset_submenu(self.breakdown_item)
        for heading, models, extra in (
            ("Today", today_models, 0),
            ("Lifetime", lifetime_models, earlier),
        ):
            self.breakdown_item.add(_bold_menu_item(heading))
            categories = _merge_cache_writes(category_totals(models))
            whole = sum(categories.values()) + extra
            for key, label in CATEGORY_LABELS:
                count = categories[key]
                self.breakdown_item.add(
                    _info_item(f"{label}: {count:,} ({_percent(count, whole)})")
                )
            if extra:
                self.breakdown_item.add(
                    _info_item(f"Older, no detail: {extra:,} ({_percent(extra, whole)})")
                )
            self.breakdown_item.add(None)
        self.breakdown_item.add(
            _info_item("Cache read = context re-sent each turn, billed cheaply")
        )

        # By Model
        self._reset_submenu(self.models_item)
        for heading, models in (("Today", today_models), ("Lifetime", lifetime_models)):
            self.models_item.add(_bold_menu_item(heading))
            rows = model_totals(models)
            if not rows:
                self.models_item.add(_info_item("No usage yet"))
            for model, tokens in rows:
                self.models_item.add(
                    _info_item(f"{_model_display_name(model)} — {format_count(tokens)}")
                )
            self.models_item.add(None)
        if earlier:
            self.models_item.add(
                _info_item(f"Plus {format_count(earlier)} older tokens with no model detail")
            )

        # Top Projects
        self._reset_submenu(self.projects_item)
        projects = top_projects(daily, week_start, today)
        if not projects:
            self.projects_item.add(_info_item("No usage in the last 7 days"))
        for project, tokens in projects:
            self.projects_item.add(_info_item(f"{project} — {format_count(tokens)}"))

        # History
        self._reset_submenu(self.history_item)
        stats = history(daily, today)
        self.history_item.add(_info_item(f"Yesterday: {stats['yesterday']:,}"))
        self.history_item.add(_info_item(f"Last 7 days: {stats['last_7_days']:,}"))
        self.history_item.add(_info_item(f"This month: {stats['this_month']:,}"))
        if stats["biggest_day"]:
            best_date, best_tokens = stats["biggest_day"]
            self.history_item.add(
                _info_item(
                    f"Biggest day: {_format_tracking_date(best_date.isoformat())} "
                    f"— {format_count(best_tokens)}"
                )
            )

        # Estimated API Cost
        self._reset_submenu(self.cost_item)
        unpriced_total = 0
        for label, models in (
            ("Today", today_models),
            ("Last 7 days", week_models),
            ("This month", month_models),
            ("All logged usage", lifetime_models),
        ):
            dollars, unpriced = estimate_cost(models)
            unpriced_total = max(unpriced_total, unpriced)
            self.cost_item.add(_info_item(f"{label}: {format_dollars(dollars)}"))
        self.cost_item.add(None)
        if unpriced_total:
            self.cost_item.add(
                _info_item(f"{format_count(unpriced_total)} tokens from unknown models not priced")
            )
        if earlier:
            self.cost_item.add(
                _info_item(f"{format_count(earlier)} older tokens not priced (no model detail)")
            )
        self.cost_item.add(
            _info_item("Estimate at API list prices. Claude Pro is flat-rate,")
        )
        self.cost_item.add(_info_item("so you aren't billed this."))

    def _since_label(self):
        return f"Tracking since: {_format_tracking_date(self.state['first_seen_at'])}"

    def _interval_label(self):
        return f"Scans every {_format_interval(self.state['scan_interval_seconds'])}"

    def _update_sessions_menu(self):
        if self.sessions_item:
            self.sessions_item.clear()
        sessions = active_sessions()
        if not sessions:
            self.sessions_item.add(rumps.MenuItem("No active sessions"))
            return
        for session in sessions:
            label = f"{session['label']} — {format_count(session['tokens'])} tokens"
            self.sessions_item.add(rumps.MenuItem(label))

    def _leaderboard_payload(self):
        yesterday = date.today() - timedelta(days=1)
        return {
            "name": self.state.get("leaderboard_name") or "Anonymous",
            "total_tokens": self.state["grand_total"],
            "yesterday_tokens": sum_usage_for_today(today=yesterday),
            "updated_at": date.today().isoformat(),
        }

    def _rebuild_leaderboard_menu(self):
        if self.leaderboard_item:
            self.leaderboard_item.clear()

        if self.state.get("my_gist_id"):
            self.leaderboard_item.add(
                rumps.MenuItem("Share Friend Code", callback=self.share_friend_code)
            )
            self.leaderboard_item.add(
                rumps.MenuItem("Push Update Now", callback=self.push_leaderboard_update)
            )
        else:
            self.leaderboard_item.add(
                rumps.MenuItem(
                    "Get Set Up with Leaderboard", callback=self.start_leaderboard_setup
                )
            )
        self.leaderboard_item.add(
            rumps.MenuItem("Add Friend by Code", callback=self.add_friend_by_code)
        )
        self.leaderboard_item.add(
            rumps.MenuItem("Pull Latest Now", callback=self.pull_leaderboard_updates)
        )
        self.leaderboard_item.add(None)

        view = self.state["leaderboard_view"]
        total_option = rumps.MenuItem(
            "Leaderboard by Total", callback=self.set_leaderboard_view
        )
        total_option.view = "total"
        total_option.state = view == "total"
        day_option = rumps.MenuItem(
            "Leaderboard by Day", callback=self.set_leaderboard_view
        )
        day_option.view = "day"
        day_option.state = view == "day"
        self.leaderboard_item.add(total_option)
        self.leaderboard_item.add(day_option)
        self.leaderboard_item.add(None)

        friends = sorted_friends(load_friends(), by=view)
        if not friends:
            self.leaderboard_item.add(rumps.MenuItem("No friends added yet"))
        else:
            metric_key = "total_tokens" if view == "total" else "yesterday_tokens"
            for friend in friends:
                label = f"{friend['name']} — {format_count(friend.get(metric_key, 0))} tokens"
                self.leaderboard_item.add(rumps.MenuItem(label))

        self.leaderboard_item.add(None)
        self.leaderboard_item.add(
            rumps.MenuItem(
                "Note: leaderboard numbers can be manipulated by people. "
                "Don't be a loser. This is just for fun."
            )
        )

    def start_leaderboard_setup(self, _):
        proceed = rumps.alert(
            "Set Up Leaderboard (Beta)",
            "This opens GitHub in your browser to create a personal access "
            "token scoped only to 'gist'. Generate it, then come back here "
            "and paste it in.",
            ok="Open GitHub",
            cancel="Cancel",
        )
        if not proceed:
            return
        webbrowser.open(NEW_TOKEN_URL)

        token_response = rumps.Window(
            message="Paste your GitHub token here:",
            title="GitHub Token",
            ok="Continue",
            cancel="Cancel",
            secure=True,
        ).run()
        if not token_response.clicked or not token_response.text.strip():
            return
        token = token_response.text.strip()

        name_response = rumps.Window(
            message="What name should show on the leaderboard?",
            title="Your Leaderboard Name",
            default_text=os.environ.get("USER", ""),
            ok="Continue",
            cancel="Cancel",
        ).run()
        if not name_response.clicked or not name_response.text.strip():
            return
        self.state["leaderboard_name"] = name_response.text.strip()

        try:
            set_github_token(token)
            gist_id = create_gist(token, self._leaderboard_payload())
        except (subprocess.CalledProcessError, urllib.error.URLError, KeyError) as e:
            rumps.alert("Setup Failed", str(e))
            return

        self.state["my_gist_id"] = gist_id
        save_state(self.state, STATE_FILE)
        self._rebuild_leaderboard_menu()
        rumps.alert("All Set", f"Your friend code is:\n\n{gist_id}")

    def share_friend_code(self, _):
        rumps.alert("Your Friend Code", self.state.get("my_gist_id", ""))

    def push_leaderboard_update(self, _=None):
        gist_id = self.state.get("my_gist_id")
        if not gist_id:
            return
        token = get_github_token()
        if not token:
            rumps.alert(
                "Leaderboard", "No GitHub token found -- run Get Set Up again."
            )
            return
        try:
            update_gist(token, gist_id, self._leaderboard_payload())
        except urllib.error.URLError as e:
            rumps.alert("Push Failed", str(e))

    def add_friend_by_code(self, _):
        response = rumps.Window(
            message="Paste your friend's Gist ID (their friend code):",
            title="Add Friend",
            ok="Add",
            cancel="Cancel",
        ).run()
        if not response.clicked or not response.text.strip():
            return
        gist_id = response.text.strip()
        friends = load_friends()
        if any(f.get("gist_id") == gist_id for f in friends):
            return
        friends.append(
            {"gist_id": gist_id, "name": gist_id, "total_tokens": 0, "yesterday_tokens": 0}
        )
        save_friends(friends)
        self.pull_leaderboard_updates()

    def pull_leaderboard_updates(self, _=None):
        friends = load_friends()
        updated = []
        for friend in friends:
            try:
                data = fetch_gist(friend["gist_id"])
            except (urllib.error.URLError, KeyError):
                updated.append(friend)
                continue
            updated.append(
                {
                    "gist_id": friend["gist_id"],
                    "name": data.get("name", friend.get("name", "Friend")),
                    "total_tokens": data.get("total_tokens", 0),
                    "yesterday_tokens": data.get("yesterday_tokens", 0),
                }
            )
        save_friends(updated)
        self._rebuild_leaderboard_menu()

    def _maybe_run_daily_leaderboard_sync(self):
        today = date.today().isoformat()
        if self.state.get("last_leaderboard_sync_date") == today:
            return
        self.push_leaderboard_update()
        self.pull_leaderboard_updates()
        self.state["last_leaderboard_sync_date"] = today
        save_state(self.state, STATE_FILE)

    def set_leaderboard_view(self, sender):
        self.state["leaderboard_view"] = sender.view
        save_state(self.state, STATE_FILE)
        self._rebuild_leaderboard_menu()

    def refresh(self, _):
        refresh_grand_total(self.state)
        save_state(self.state, STATE_FILE)
        self._update_title()
        self.total_item.title = self._total_label()
        self.today_item.title = self._today_label()
        self._rebuild_stats_menus()
        self._update_sessions_menu()
        self._maybe_run_daily_leaderboard_sync()
        self._rebuild_leaderboard_menu()

    def toggle_pause(self, sender):
        if self.timer.is_alive():
            self.timer.stop()
            sender.title = "Resume Scanning"
        else:
            self.timer.start()
            sender.title = "Pause Scanning"

    def set_scan_interval(self, sender):
        for option in self.interval_item.values():
            option.state = False
        sender.state = True
        self.state["scan_interval_seconds"] = sender.interval_seconds
        save_state(self.state, STATE_FILE)
        self.interval_item.title = self._interval_label()

        # Timer.interval's setter silently no-ops if the current interval
        # hasn't elapsed yet, so swap in a fresh Timer instead of relying on it.
        was_alive = self.timer.is_alive()
        if was_alive:
            self.timer.stop()
        self.timer = rumps.Timer(self.refresh, sender.interval_seconds)
        if was_alive:
            self.timer.start()

    def toggle_start_at_login(self, sender):
        new_value = not sender.state
        try:
            set_start_at_login(new_value)
        except subprocess.CalledProcessError as e:
            rumps.alert("Couldn't update login setting", str(e))
            return
        sender.state = new_value
        self.state["start_at_login"] = new_value
        save_state(self.state, STATE_FILE)


def hide_dock_icon():
    # Accessory policy = menu-bar only: no Dock icon, no app menu, not in Cmd-Tab.
    NSApplication.sharedApplication().setActivationPolicy_(
        NSApplicationActivationPolicyAccessory
    )


if __name__ == "__main__":
    hide_dock_icon()
    TokenCounterApp().run()
