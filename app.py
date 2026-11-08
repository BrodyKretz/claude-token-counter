import os
import subprocess
import sys
import threading
import urllib.error
import webbrowser
from datetime import date, datetime, timedelta
from pathlib import Path

import rumps
from PyObjCTools import AppHelper
from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSAttributedString,
    NSFont,
    NSFontAttributeName,
    NSImageLeft,
)

from accounts import KEY_HELP, account_due, delete_key, fetch_account, load_key, save_key, store_result
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
    view_choices,
    welcome_tab,
)
from token_math import (
    backfill_daily,
    format_count,
    load_state,
    save_state,
    sum_usage_for_today,
)
from tool_icons import menu_bar_image
from providers import PROVIDER_NAMES, PROVIDERS, provider_view, tools_to_scan
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


def init_provider_state(state):
    """Provider tracking starts off; nothing already in `state` changes."""
    state.setdefault("enabled_providers", [])
    state.setdefault("provider_keys", [])  # which providers have a key in the Keychain


def menu_bar_label(view_key, count_text, has_icon):
    """(text, show_icon) for the menu bar. A single tool shows its own icon
    when one was found; the combined view (or a missing icon) shows the coin.
    `count_text` is None in icon-only mode."""
    use_icon = view_key != "all" and has_icon
    if use_icon:
        return (f" {count_text}" if count_text else ""), True
    return (f"🪙 {count_text}" if count_text else "🪙"), False


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
        init_provider_state(self.state)
        self._fetching = set()  # providers with an account fetch in flight
        self._fetched = []  # (provider, result) waiting to be saved on the main thread
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
        self._scan()
        save_state(self.state, STATE_FILE)
        self._fetch_accounts()

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

    def _scan(self, detected=None):
        scan_tools(self.state, tools_to_scan(self.state, detected or detect_tools()))

    def _current_view(self, detected=None):
        """The view the panel and menu bar show: the selected tool or
        provider, or every enabled tool combined."""
        enabled = self.state["enabled_tools"]
        choices = [key for key, _ in view_choices(self.state, detected or detect_tools())]
        if not choices:
            return combined_view(self.state, enabled)
        selected = self.state["selected_tool"]
        key = selected if selected in choices else choices[0]
        if key == "all":
            return combined_view(self.state, enabled)
        if key in PROVIDER_NAMES:
            return provider_view(self.state, key)
        return tool_view(self.state, key)

    def _sessions_for(self, view):
        if view["key"] in PROVIDER_NAMES:
            return []
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
            count = format_count(total_in_range(view["daily"], today, today))
        elif mode == "icon":
            count = None
        else:
            count = format_count(view["grand_total"])
        image = menu_bar_image(view["key"]) if view["key"] != "all" else None
        title, show_icon = menu_bar_label(view["key"], count, image is not None)
        self.title = title
        # Redraw it at the size picked in Settings, with even-width digits so
        # the item doesn't jiggle as the count changes.
        status_item = getattr(getattr(self, "_nsapp", None), "nsstatusitem", None)
        if status_item is not None:
            font = NSFont.monospacedDigitSystemFontOfSize_weight_(
                self.state["menu_bar_font_size"], 0.0
            )
            button = status_item.button()
            button.setAttributedTitle_(
                NSAttributedString.alloc().initWithString_attributes_(
                    title, {NSFontAttributeName: font}
                )
            )
            button.setImage_(image if show_icon else None)
            button.setImagePosition_(NSImageLeft)

    def _render_panel(self):
        detected = detect_tools()
        view = self._current_view(detected)
        choices = view_choices(self.state, detected)
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
        provider_dialogs = {
            "provider_key": self.add_api_key,
            "provider_key_remove": self.remove_api_key,
        }
        name, _, argument = action.partition(":")
        if action == "quit":
            rumps.quit_application()
            return
        if action in dialogs:
            # Dialogs can't sit on top of the popover, so close it first.
            self.panel.close()
            dialogs[action]()
        elif name in provider_dialogs and argument in PROVIDER_NAMES:
            self.panel.close()
            provider_dialogs[name](argument)
        elif name == "provider" and argument in PROVIDER_NAMES:
            self.set_provider_enabled(argument, value)
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
            choices = view_choices(self.state, detect_tools())
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
        self._scan()
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

    def set_provider_enabled(self, key, enabled):
        order = [k for k, _ in PROVIDERS]
        providers = set(self.state["enabled_providers"])
        providers = providers | {key} if enabled else providers - {key}
        self.state["enabled_providers"] = sorted(providers, key=order.index)
        if enabled:
            self._scan()  # a provider's models may be in tools not enabled yet
            self._fetch_accounts()
        save_state(self.state, STATE_FILE)
        self._update_title()

    def add_api_key(self, provider):
        name = PROVIDER_NAMES[provider]
        response = rumps.Window(
            message=(f"Paste your {name} API key. It's stored only in this Mac's "
                     f"Keychain and sent only to {name}.\n\n{KEY_HELP[provider]}."),
            title=f"{name} API Key",
            ok="Save",
            cancel="Cancel",
            secure=True,
        ).run()
        if not response.clicked or not response.text.strip():
            return
        try:
            save_key(provider, response.text)
        except (ValueError, OSError) as e:
            rumps.alert("Key Not Saved", str(e))
            return
        keys = set(self.state["provider_keys"]) | {provider}
        self.state["provider_keys"] = [k for k, _ in PROVIDERS if k in keys]
        self.state.get("accounts", {}).pop(provider, None)  # numbers from an older key
        save_state(self.state, STATE_FILE)
        self._fetch_accounts(force=provider)

    def remove_api_key(self, provider):
        name = PROVIDER_NAMES[provider]
        confirmed = rumps.alert(
            f"Remove {name} API Key?",
            f"This deletes the key from this Mac's Keychain. To see {name} account "
            "numbers again you'll need to paste it again.",
            ok="Remove",
            cancel="Cancel",
        )
        if not confirmed:
            return
        delete_key(provider)
        self.state["provider_keys"] = [k for k in self.state["provider_keys"] if k != provider]
        self.state.get("accounts", {}).pop(provider, None)
        save_state(self.state, STATE_FILE)
        self._render_panel()

    def _fetch_accounts(self, force=None):
        """Start a background fetch for each enabled provider with a key whose
        numbers are due (every 15 minutes) or `force`d."""
        saved = self.state.get("accounts", {})
        for key in self.state["enabled_providers"]:
            if key not in self.state["provider_keys"] or key in self._fetching:
                continue
            if key != force and not account_due(saved.get(key)):
                continue
            self._fetching.add(key)
            threading.Thread(target=self._fetch_account, args=(key,), daemon=True).start()

    def _fetch_account(self, provider):
        """Runs on a background thread; the result is saved on the main thread."""
        try:
            api_key = load_key(provider)
            if api_key:
                result = fetch_account(provider, api_key)
            else:
                result = {"error": "the key is no longer in the Keychain"}
        except Exception as e:  # keep the fetch from being stuck "in flight"
            result = {"error": f"unexpected problem ({type(e).__name__})"}
        if result["error"] and "fetched_at" not in result:
            result = {"daily": {}, "cost": {}, "rows": [], "notes": [], **result,
                      "fetched_at": datetime.now().isoformat(timespec="seconds")}
        self._fetched.append((provider, result))
        AppHelper.callAfter(self._show_fetched_accounts)

    def _show_fetched_accounts(self):
        self._save_fetched_accounts()
        save_state(self.state, STATE_FILE)
        self._render_panel()

    def _save_fetched_accounts(self):
        while self._fetched:
            provider, result = self._fetched.pop(0)
            self._fetching.discard(provider)
            if provider in self.state["provider_keys"]:  # not removed meanwhile
                store_result(self.state, provider, result)

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
        self._scan()
        self._save_fetched_accounts()
        save_state(self.state, STATE_FILE)
        self._fetch_accounts()
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
