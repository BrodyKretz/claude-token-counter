import os
import subprocess
from datetime import date
from pathlib import Path

import rumps

from active_sessions import active_sessions
from token_math import format_count, load_state, refresh_grand_total, save_state

STATE_FILE = Path(__file__).resolve().parent / "state.json"
REFRESH_SECONDS = 15
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
        super().__init__("Claude Tokens", quit_button="Quit")
        self.state = load_state(STATE_FILE)
        self.state.setdefault("first_seen_at", None)
        self.state.setdefault("start_at_login", True)
        if self.state["first_seen_at"] is None:
            self.state["first_seen_at"] = date.today().isoformat()
        refresh_grand_total(self.state)
        save_state(self.state, STATE_FILE)

        self.total_item = rumps.MenuItem(self._total_label())
        self.since_item = rumps.MenuItem(self._since_label())
        self.sessions_item = rumps.MenuItem("Active Sessions")
        self.pause_item = rumps.MenuItem("Pause Scanning", callback=self.toggle_pause)
        self.login_item = rumps.MenuItem(
            "Start at Login", callback=self.toggle_start_at_login
        )
        self.login_item.state = self.state["start_at_login"]

        self.menu = [
            self.total_item,
            self.since_item,
            None,
            self.sessions_item,
            None,
            self.pause_item,
            self.login_item,
        ]
        self._update_sessions_menu()
        self.title = f"🪙 {format_count(self.state['grand_total'])}"

        self.timer = rumps.Timer(self.refresh, REFRESH_SECONDS)
        self.timer.start()

    def _total_label(self):
        return f"Claude tokens used: {self.state['grand_total']:,}"

    def _since_label(self):
        return f"Tracking since: {self.state['first_seen_at']}"

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

    def refresh(self, _):
        refresh_grand_total(self.state)
        save_state(self.state, STATE_FILE)
        self.title = f"🪙 {format_count(self.state['grand_total'])}"
        self.total_item.title = self._total_label()
        self._update_sessions_menu()

    def toggle_pause(self, sender):
        if self.timer.is_alive():
            self.timer.stop()
            sender.title = "Resume Scanning"
        else:
            self.timer.start()
            sender.title = "Pause Scanning"

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
