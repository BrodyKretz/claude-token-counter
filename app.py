import os
import subprocess
import sys
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

from active_sessions import active_sessions, running_tool_sessions
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
from single_instance import acquire_lock, observe_show_requests, request_show_panel
from stats_tabs import (
    DEFAULT_MENU_BAR_FONT_SIZE,
    LEADERBOARD_VIEWS,
    MENU_BAR_FONT_SIZES,
    TITLE_MODES,
    build_panel,
    format_long_date,
    leaderboard_enabled,
    settings_tab,
    tool_choices,
    welcome_tab,
)
from token_math import (
    backfill_daily,
    format_count,
    load_state,
    save_state,
    sum_usage_for_today,
)
from tools import TOOLS, combined_view, detect_tools, scan_tools, tool_view
from usage_stats import total_in_range
from version import APP_NAME, REPO_URL

STATE_FILE = Path(__file__).resolve().parent / "state.json"
LOCK_FILE = Path(__file__).resolve().parent / ".claude-tracker.lock"
REFRESH_SECONDS = 15
SCAN_INTERVAL_CHOICES = [5, 15, 30, 60, 300]
LABEL = "com.claudetokencounter.menubar"


def init_tool_state(state, fresh_install):
    """Add the multi-tool settings to `state` without touching anything
    already there. Existing installs keep tracking just Claude Code and skip
    the welcome picker; fresh installs track nothing until a tool is chosen."""
    state.setdefault("enabled_tools", [] if fresh_install else ["claude_code"])
    state.setdefault("combine_tools", False)
    state.setdefault(
        "selected_tool", state["enabled_tools"][0] if state["enabled_tools"] else "claude_code"
    )
    state.setdefault("onboarding_done", not fresh_install)


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
        super().__init__(APP_NAME, quit_button=None)
        fresh_install = not STATE_FILE.exists()
        self.state = load_state(STATE_FILE)
        init_tool_state(self.state, fresh_install)
        self.welcome_choice = []
        self.state.setdefault("first_seen_at", None)
        self.state.setdefault("start_at_login", True)
        self.state.setdefault("scan_interval_seconds", REFRESH_SECONDS)
        self.state.setdefault("leaderboard_view", "total")
        self.state.setdefault("my_gist_id", None)
        self.state.setdefault("leaderboard_name", None)
        self.state.setdefault("last_leaderboard_sync_date", None)
        self.state.setdefault("title_mode", "lifetime")
        self.state.setdefault("menu_bar_font_size", DEFAULT_MENU_BAR_FONT_SIZE)
        self.state.setdefault("panel_tab", "overview")
        self.state.pop("stats_tab", None)  # from the earlier in-menu tabs
        if self.state["first_seen_at"] is None:
            self.state["first_seen_at"] = date.today().isoformat()
        # Backfill must run before the first refresh: it re-reads each file
        # only up to the offsets saved by the previous run.
        backfill_daily(self.state)
        scan_tools(self.state, self.state["enabled_tools"])
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
        # Opening the app again (e.g. from Finder) asks this copy to show its panel.
        self._show_observer = observe_show_requests(self.panel.show)
        self._update_title()
        if not self.state["onboarding_done"]:
            self.panel.show()  # first run: ask which tools to track

    def _current_view(self, detected=None):
        """The view the panel and menu bar show: the selected tool, or every
        enabled tool combined."""
        enabled = self.state["enabled_tools"]
        if self.state["combine_tools"]:
            return combined_view(self.state, enabled)
        choices = [key for key, _ in tool_choices(self.state, detected or detect_tools())]
        if not choices:
            return combined_view(self.state, enabled)
        selected = self.state["selected_tool"]
        return tool_view(self.state, selected if selected in choices else choices[0])

    def _sessions_for(self, view):
        keys = [view["key"]] if view["key"] != "all" else self.state["enabled_tools"]
        sessions = []
        for key in keys:
            sessions += active_sessions() if key == "claude_code" else running_tool_sessions(key)
        return sessions

    def _update_title(self):
        view = self._current_view()
        mode = self.state["title_mode"]
        if mode == "today":
            today = date.today()
            title = f"🪙 {format_count(total_in_range(view['daily'], today, today))}"
        elif mode == "icon":
            title = "🪙"
        else:
            title = f"🪙 {format_count(view['grand_total'])}"
        self.title = title
        # Redraw it at the size picked in Settings, with even-width digits so
        # the item doesn't jiggle as the count changes.
        status_item = getattr(getattr(self, "_nsapp", None), "nsstatusitem", None)
        if status_item is not None:
            font = NSFont.monospacedDigitSystemFontOfSize_weight_(
                self.state["menu_bar_font_size"], 0.0
            )
            status_item.button().setAttributedTitle_(
                NSAttributedString.alloc().initWithString_attributes_(
                    title, {NSFontAttributeName: font}
                )
            )

    def _render_panel(self):
        detected = detect_tools()
        view = self._current_view(detected)
        choices = [] if self.state["combine_tools"] else tool_choices(self.state, detected)
        friends = sorted_friends(load_friends(), by=self.state["leaderboard_view"])
        self.panel.render(
            build_panel(
                view, self.state, self._sessions_for(view), friends,
                leaderboard_enabled(self.state) and view["key"] == "claude_code",
            ),
            settings_tab(self.state, self.paused, SCAN_INTERVAL_CHOICES, detected),
            f"Tracking since {format_long_date(self.state['first_seen_at'])}",
            self.paused,
            tool_choices=choices,
            selected_tool=view["key"],
            welcome=None if self.state["onboarding_done"]
            else welcome_tab(detected, self.welcome_choice),
            subtitle="All AI tools" if view["key"] == "all" else f"for {view['name']}",
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
        elif action == "menu_bar_font_size":
            self.state["menu_bar_font_size"] = MENU_BAR_FONT_SIZES[value]
            save_state(self.state, STATE_FILE)
            self._update_title()
        elif action == "scan_interval":
            self.set_scan_interval(SCAN_INTERVAL_CHOICES[value])
        elif action == "pause":
            self.set_paused(value)
        elif action == "login":
            self.set_start_at_login(value)
        elif action == "leaderboard_enabled":
            self.state["leaderboard_enabled"] = value
            save_state(self.state, STATE_FILE)
        elif action == "open_repo":
            self.panel.close()
            webbrowser.open(REPO_URL)
        elif action == "select_tool":
            choices = tool_choices(self.state, detect_tools())
            self.state["selected_tool"] = choices[value][0]
            save_state(self.state, STATE_FILE)
            self._update_title()
        elif action.startswith("welcome_tool:"):
            key = action.split(":", 1)[1]
            self.welcome_choice = [k for k in self.welcome_choice if k != key] + ([key] if value else [])
        elif action == "welcome_done":
            self.finish_welcome()
        elif action.startswith("tool:"):
            self.set_tool_enabled(action.split(":", 1)[1], value)
        elif action == "combine_tools":
            self.state["combine_tools"] = value
            save_state(self.state, STATE_FILE)
            self._update_title()
        self._render_panel()

    def finish_welcome(self):
        order = [key for key, _ in TOOLS]
        self.state["enabled_tools"] = sorted(self.welcome_choice, key=order.index)
        if self.state["enabled_tools"]:
            self.state["selected_tool"] = self.state["enabled_tools"][0]
        self.state["onboarding_done"] = True
        scan_tools(self.state, self.state["enabled_tools"])
        save_state(self.state, STATE_FILE)
        self._update_title()

    def set_tool_enabled(self, key, enabled):
        order = [k for k, _ in TOOLS]
        tools = set(self.state["enabled_tools"])
        tools = tools | {key} if enabled else tools - {key}
        self.state["enabled_tools"] = sorted(tools, key=order.index)
        if enabled:
            scan_tools(self.state, [key])
        save_state(self.state, STATE_FILE)
        self._update_title()

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
        if not leaderboard_enabled(self.state):
            return
        if self.state.get("last_leaderboard_sync_date") == today:
            return
        self.push_leaderboard_update()
        self.pull_leaderboard_updates()
        self.state["last_leaderboard_sync_date"] = today
        save_state(self.state, STATE_FILE)

    def refresh(self, _):
        scan_tools(self.state, self.state["enabled_tools"])
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
    instance_lock = acquire_lock(LOCK_FILE)
    if instance_lock is None:
        # Already running (e.g. started at login): show that copy's panel.
        request_show_panel()
        sys.exit(0)
    hide_dock_icon()
    TokenCounterApp().run()
