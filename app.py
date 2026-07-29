import os
import subprocess
from datetime import date
from pathlib import Path

import rumps
from AppKit import NSAttributedString, NSFont, NSFontAttributeName

from active_sessions import active_sessions
from leaderboard import load_friends, sorted_friends
from token_math import (
    format_count,
    load_state,
    refresh_grand_total,
    save_state,
    sum_usage_for_today,
)

STATE_FILE = Path(__file__).resolve().parent / "state.json"
REFRESH_SECONDS = 15
SCAN_INTERVAL_CHOICES = [5, 15, 30, 60, 300]
LABEL = "com.claudetokencounter.menubar"


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
        if self.state["first_seen_at"] is None:
            self.state["first_seen_at"] = date.today().isoformat()
        refresh_grand_total(self.state)
        save_state(self.state, STATE_FILE)

        self.header_item = _bold_menu_item("Token Tracker for Claude Code")
        self.total_item = rumps.MenuItem(self._total_label())
        self.today_item = rumps.MenuItem(self._today_label())
        self.since_item = rumps.MenuItem(self._since_label())
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
            self.leaderboard_item,
            self.sessions_item,
            None,
            self.pause_item,
            self.interval_item,
            self.login_item,
        ]
        self._update_sessions_menu()
        self._rebuild_leaderboard_menu()
        self.title = f"🪙 {format_count(self.state['grand_total'])}"

        self.timer = rumps.Timer(self.refresh, self.state["scan_interval_seconds"])
        self.timer.start()

    def _total_label(self):
        return f"Claude tokens used: {self.state['grand_total']:,}"

    def _today_label(self):
        return f"Today's tokens used: {sum_usage_for_today():,}"

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

    def _rebuild_leaderboard_menu(self):
        if self.leaderboard_item:
            self.leaderboard_item.clear()
        self.leaderboard_item.add(
            rumps.MenuItem("Invite Friend", callback=self.invite_friend)
        )
        self.leaderboard_item.add(
            rumps.MenuItem("Share Friend Code", callback=self.share_friend_code)
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

    def invite_friend(self, _):
        rumps.alert(
            "Invite Friend (Beta)",
            "Friend syncing isn't built yet -- this button is a placeholder "
            "for a feature that's still in progress.",
        )

    def share_friend_code(self, _):
        rumps.alert(
            "Share Friend Code (Beta)",
            "Friend codes aren't built yet -- this button is a placeholder "
            "for a feature that's still in progress.",
        )

    def set_leaderboard_view(self, sender):
        self.state["leaderboard_view"] = sender.view
        save_state(self.state, STATE_FILE)
        self._rebuild_leaderboard_menu()

    def refresh(self, _):
        refresh_grand_total(self.state)
        save_state(self.state, STATE_FILE)
        self.title = f"🪙 {format_count(self.state['grand_total'])}"
        self.total_item.title = self._total_label()
        self.today_item.title = self._today_label()
        self._update_sessions_menu()
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


if __name__ == "__main__":
    TokenCounterApp().run()
