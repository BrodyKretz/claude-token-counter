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
from stats_panel import StatsPanel
from stats_tabs import build_tabs, format_long_date
from token_math import (
    backfill_daily,
    format_count,
    load_state,
    refresh_grand_total,
    save_state,
    sum_usage_for_today,
)
from usage_stats import total_in_range

STATE_FILE = Path(__file__).resolve().parent / "state.json"
REFRESH_SECONDS = 15
SCAN_INTERVAL_CHOICES = [5, 15, 30, 60, 300]
LABEL = "com.claudetokencounter.menubar"

TITLE_MODES = [
    ("lifetime", "Lifetime Total"),
    ("today", "Today's Total"),
    ("icon", "Icon Only"),
]


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
        self.state.setdefault("stats_tab", 0)
        self.stats_panel = StatsPanel(
            selected_tab=self.state["stats_tab"], on_tab_change=self.set_stats_tab
        )
        # rumps wraps NSMenuItems; swap in the panel's view-backed item.
        self.stats_item = rumps.MenuItem("Stats")
        self.stats_item._menuitem = self.stats_panel.menuitem
        self.title_mode_item = rumps.MenuItem("Menu Bar Shows")
        for mode, label in TITLE_MODES:
            option = rumps.MenuItem(label, callback=self.set_title_mode)
            option.mode = mode
            option.state = mode == self.state["title_mode"]
            self.title_mode_item.add(option)
        self.leaderboard_item = rumps.MenuItem("Leaderboard (Beta)")
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
            self.stats_item,
            None,
            self.leaderboard_item,
            None,
            self.title_mode_item,
            self.pause_item,
            self.interval_item,
            self.login_item,
        ]
        self._rebuild_leaderboard_menu()
        self._update_stats_panel()
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

    def _since_label(self):
        return f"Tracking since: {format_long_date(self.state['first_seen_at'])}"

    def _interval_label(self):
        return f"Scans every {_format_interval(self.state['scan_interval_seconds'])}"

    def _update_stats_panel(self):
        self.stats_panel.update(build_tabs(self.state, active_sessions()))

    def set_stats_tab(self, index):
        self.state["stats_tab"] = index
        save_state(self.state, STATE_FILE)

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
        self._update_stats_panel()
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
