import os
import subprocess
import urllib.error
import webbrowser
from datetime import date, timedelta
from pathlib import Path

import rumps
from AppKit import NSApplication, NSApplicationActivationPolicyAccessory

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
from panel_view import Panel
from stats_tabs import (
    LEADERBOARD_VIEWS,
    TITLE_MODES,
    build_panel,
    format_long_date,
    settings_tab,
)
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
        super().__init__("Claude Tokens", quit_button=None)
        self.state = load_state(STATE_FILE)
        self.state.setdefault("first_seen_at", None)
        self.state.setdefault("start_at_login", True)
        self.state.setdefault("scan_interval_seconds", REFRESH_SECONDS)
        self.state.setdefault("leaderboard_view", "total")
        self.state.setdefault("my_gist_id", None)
        self.state.setdefault("leaderboard_name", None)
        self.state.setdefault("last_leaderboard_sync_date", None)
        self.state.setdefault("title_mode", "lifetime")
        self.state.setdefault("panel_tab", "overview")
        self.state.pop("stats_tab", None)  # from the earlier in-menu tabs
        if self.state["first_seen_at"] is None:
            self.state["first_seen_at"] = date.today().isoformat()
        # Backfill must run before the first refresh: it re-reads each file
        # only up to the offsets saved by the previous run.
        backfill_daily(self.state)
        refresh_grand_total(self.state)
        save_state(self.state, STATE_FILE)

        self.paused = False
        self.panel = Panel(
            on_action=self.handle_action,
            on_tab_change=self.set_panel_tab,
            selected_tab=self.state["panel_tab"],
        )
        self._render_panel()
        self._update_title()
        # rumps creates the status item inside run(); swap its menu for the
        # panel once it exists.
        rumps.events.before_start.register(self._attach_panel)

        self.timer = rumps.Timer(self.refresh, self.state["scan_interval_seconds"])
        self.timer.start()

    def _attach_panel(self):
        self.panel.attach(self._nsapp.nsstatusitem)

    def _today_tokens(self):
        today = date.today()
        return total_in_range(self.state["daily"], today, today)

    def _update_title(self):
        mode = self.state["title_mode"]
        if mode == "today":
            self.title = f"🪙 {format_count(self._today_tokens())}"
        elif mode == "icon":
            self.title = "🪙"
        else:
            self.title = f"🪙 {format_count(self.state['grand_total'])}"

    def _render_panel(self):
        view = self.state["leaderboard_view"]
        self.panel.render(
            build_panel(self.state, active_sessions(), sorted_friends(load_friends(), by=view)),
            settings_tab(self.state, self.paused, SCAN_INTERVAL_CHOICES),
            f"Tracking since {format_long_date(self.state['first_seen_at'])}",
            self.paused,
        )

    def set_panel_tab(self, key):
        self.state["panel_tab"] = key
        save_state(self.state, STATE_FILE)

    def handle_action(self, action, value):
        """Called by the panel when a button, switch or picker is used."""
        dialogs = {
            "leaderboard_setup": self.start_leaderboard_setup,
            "leaderboard_share": self.share_friend_code,
            "leaderboard_add": self.add_friend_by_code,
        }
        if action == "quit":
            rumps.quit_application()
            return
        if action in dialogs:
            # Dialogs can't sit on top of the popover, so close it first.
            self.panel.close()
            dialogs[action]()
        elif action == "leaderboard_push":
            self.push_leaderboard_update()
        elif action == "leaderboard_pull":
            self.pull_leaderboard_updates()
        elif action == "leaderboard_view":
            self.state["leaderboard_view"] = LEADERBOARD_VIEWS[value][0]
            save_state(self.state, STATE_FILE)
        elif action == "title_mode":
            self.state["title_mode"] = TITLE_MODES[value][0]
            save_state(self.state, STATE_FILE)
            self._update_title()
        elif action == "scan_interval":
            self.set_scan_interval(SCAN_INTERVAL_CHOICES[value])
        elif action == "pause":
            self.set_paused(value)
        elif action == "login":
            self.set_start_at_login(value)
        self._render_panel()

    def _leaderboard_payload(self):
        yesterday = date.today() - timedelta(days=1)
        return {
            "name": self.state.get("leaderboard_name") or "Anonymous",
            "total_tokens": self.state["grand_total"],
            "yesterday_tokens": sum_usage_for_today(today=yesterday),
            "updated_at": date.today().isoformat(),
        }

    def start_leaderboard_setup(self):
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
        self._render_panel()
        rumps.alert("All Set", f"Your friend code is:\n\n{gist_id}")

    def share_friend_code(self):
        rumps.alert("Your Friend Code", self.state.get("my_gist_id", ""))

    def push_leaderboard_update(self):
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

    def add_friend_by_code(self):
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

    def pull_leaderboard_updates(self):
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

    def _maybe_run_daily_leaderboard_sync(self):
        today = date.today().isoformat()
        if self.state.get("last_leaderboard_sync_date") == today:
            return
        self.push_leaderboard_update()
        self.pull_leaderboard_updates()
        self.state["last_leaderboard_sync_date"] = today
        save_state(self.state, STATE_FILE)

    def refresh(self, _):
        refresh_grand_total(self.state)
        save_state(self.state, STATE_FILE)
        self._update_title()
        self._maybe_run_daily_leaderboard_sync()
        self._render_panel()

    def set_paused(self, paused):
        self.paused = paused
        if paused and self.timer.is_alive():
            self.timer.stop()
        elif not paused and not self.timer.is_alive():
            self.timer.start()

    def set_scan_interval(self, seconds):
        self.state["scan_interval_seconds"] = seconds
        save_state(self.state, STATE_FILE)

        # Timer.interval's setter silently no-ops if the current interval
        # hasn't elapsed yet, so swap in a fresh Timer instead of relying on it.
        was_alive = self.timer.is_alive()
        if was_alive:
            self.timer.stop()
        self.timer = rumps.Timer(self.refresh, seconds)
        if was_alive:
            self.timer.start()

    def set_start_at_login(self, enabled):
        try:
            set_start_at_login(enabled)
        except subprocess.CalledProcessError as e:
            self.panel.close()
            rumps.alert("Couldn't update login setting", str(e))
            return
        self.state["start_at_login"] = enabled
        save_state(self.state, STATE_FILE)


def hide_dock_icon():
    # Accessory policy = menu-bar only: no Dock icon, no app menu, not in Cmd-Tab.
    NSApplication.sharedApplication().setActivationPolicy_(
        NSApplicationActivationPolicyAccessory
    )


if __name__ == "__main__":
    hide_dock_icon()
    TokenCounterApp().run()
