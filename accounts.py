"""Optional account numbers from each provider's own API, using an API key
the user adds in Settings.

Privacy:
- Keys are kept only in the macOS Keychain. They are written through
  `security -i` on stdin, so they never appear in a process list, and are
  never stored in state.json or logged.
- A key is sent only over HTTPS, only to its own provider's API hosts
  (ALLOWED_HOSTS), and redirects are not followed.
- Only usage numbers and balances are requested.

What a key gives:
- OpenAI admin key (sk-admin-...): daily tokens per model and billed cost.
- Kimi admin key (sk-admin-...): daily tokens per model, balance, total spent.
- Kimi API key: balance. DeepSeek API key: balance (DeepSeek has no usage
  history API).
"""

import json
import re
import subprocess
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from urllib.parse import urlencode, urlparse

from usage_stats import add_usage
from version import __version__

KEYCHAIN_SERVICE = "com.raymondtian.claudetracker.apikey"
KEY_PATTERN = re.compile(r"^[A-Za-z0-9._\-]{8,512}$")
ALLOWED_HOSTS = {
    "openai": {"api.openai.com"},
    "deepseek": {"api.deepseek.com"},
    "kimi": {"api.moonshot.ai", "api.moonshot.cn"},
}
NAMES = {"openai": "OpenAI", "deepseek": "DeepSeek", "kimi": "Kimi"}
REFRESH_SECONDS = 15 * 60
WINDOW_DAYS = 30
MAX_PAGES = 10
ACCOUNT_PROJECT = "Account"  # account APIs don't say which folder a call came from
MILLI_CENTS_PER_DOLLAR = 100_000

KEY_HELP = {
    "openai": "Needs an admin key (sk-admin-…) for usage and cost",
    "deepseek": "An API key shows your balance",
    "kimi": "An API key shows your balance; an admin key also shows usage",
}


# --- Keychain -------------------------------------------------------------

def valid_key(key):
    return bool(KEY_PATTERN.match(key or ""))


def load_key(provider, run=subprocess.run):
    result = run(
        ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", provider, "-w"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def save_key(provider, key, run=subprocess.run):
    """Store `key` in the Keychain. Raises ValueError for a malformed key and
    OSError if the Keychain didn't keep it."""
    key = (key or "").strip()
    if not valid_key(key):
        raise ValueError("That doesn't look like an API key.")
    run(
        ["security", "-i"],
        input=f"add-generic-password -U -s {KEYCHAIN_SERVICE} -a {provider} -w {key}\n",
        capture_output=True, text=True,
    )
    if load_key(provider, run=run) != key:
        raise OSError("The key couldn't be saved to the Keychain.")


def delete_key(provider, run=subprocess.run):
    run(["security", "delete-generic-password", "-s", KEYCHAIN_SERVICE, "-a", provider],
        capture_output=True, text=True)


# --- HTTP -----------------------------------------------------------------

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # a redirect becomes an HTTPError; the key never follows it


_opener = urllib.request.build_opener(_NoRedirect)


def http_get_json(url, key, provider):
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS[provider]:
        raise ValueError(f"refusing to send a {provider} key to {parsed.scheme}://{parsed.hostname}")
    request = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
        "User-Agent": f"ClaudeTracker/{__version__}",
    })
    with _opener.open(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


# --- helpers --------------------------------------------------------------

def _window_start(today):
    start = today - timedelta(days=WINDOW_DAYS - 1)
    return datetime(start.year, start.month, start.day)


def _money(amount, symbol):
    return f"{symbol}{float(amount):,.2f}"


def _parts(prompt, cached, completion):
    """Account APIs count cached tokens inside the prompt; split them out so
    totals match the provider's own."""
    cached = cached or 0
    return {
        "input": max((prompt or 0) - cached, 0),
        "output": completion or 0,
        "cache_write_5m": 0,
        "cache_write_1h": 0,
        "cache_read": cached,
    }


def _describe(error, name):
    if isinstance(error, urllib.error.HTTPError):
        if error.code in (401, 403):
            return f"the API key was rejected (HTTP {error.code})"
        if error.code == 429:
            return f"{name} is rate limiting requests; will retry"
        return f"{name} answered HTTP {error.code}"
    if isinstance(error, urllib.error.URLError):
        return f"couldn't reach {name} ({error.reason})"
    if isinstance(error, OSError):  # e.g. a timeout while reading the answer
        return f"couldn't reach {name} ({error})"
    return f"{name} sent an unexpected response"


def _pages(get, key, base, params, cursor_param, next_field):
    """Each page's JSON, following the API's cursor."""
    cursor = None
    for _ in range(MAX_PAGES):
        query = dict(params, **({cursor_param: cursor} if cursor else {}))
        page = get(f"{base}?{urlencode(query, doseq=True)}", key)
        yield page
        cursor = page.get(next_field)
        if not page.get("has_more") or not cursor:
            return


def _empty_result():
    return {"daily": {}, "cost": {}, "rows": [], "notes": [], "error": None}


# --- providers ------------------------------------------------------------

def _fetch_openai(key, today, get):
    result = _empty_result()
    if not key.startswith("sk-admin-"):
        result["error"] = ("usage needs an admin key (sk-admin-…), from "
                           "platform.openai.com → Settings → Admin keys")
        return result
    start = int(_window_start(today).timestamp())
    usage = _pages(get, key, "https://api.openai.com/v1/organization/usage/completions",
                   {"start_time": start, "bucket_width": "1d", "limit": 31, "group_by": "model"},
                   "page", "next_page")
    for page in usage:
        for bucket in page["data"]:
            day = datetime.fromtimestamp(bucket["start_time"]).date()
            for row in bucket["results"]:
                parts = _parts(row.get("input_tokens"), row.get("input_cached_tokens"),
                               row.get("output_tokens"))
                if sum(parts.values()):
                    add_usage(result["daily"], day, row.get("model") or "unknown",
                              ACCOUNT_PROJECT, parts)
    try:
        costs = _pages(get, key, "https://api.openai.com/v1/organization/costs",
                       {"start_time": start, "bucket_width": "1d", "limit": 31},
                       "page", "next_page")
        for page in costs:
            for bucket in page["data"]:
                iso = datetime.fromtimestamp(bucket["start_time"]).date().isoformat()
                for row in bucket["results"]:
                    result["cost"][iso] = result["cost"].get(iso, 0.0) + float(row["amount"]["value"])
    except (OSError, KeyError, TypeError, ValueError) as e:
        result["cost"] = {}
        result["notes"].append(f"Billed cost unavailable: {_describe(e, 'OpenAI')}")
    return result


def _fetch_deepseek(key, today, get):
    result = _empty_result()
    data = get("https://api.deepseek.com/user/balance", key)
    for info in data["balance_infos"]:
        symbol = {"CNY": "¥", "USD": "$"}.get(info["currency"], info["currency"] + " ")
        result["rows"] += [
            ["Balance", _money(info["total_balance"], symbol)],
            ["Granted", _money(info["granted_balance"], symbol)],
            ["Topped up", _money(info["topped_up_balance"], symbol)],
        ]
    if not data["is_available"]:
        result["notes"].append("Balance too low for API calls")
    result["notes"].append("DeepSeek's API reports balance only, not usage history")
    return result


def _fetch_kimi(key, today, get):
    result = _empty_result()
    if key.startswith("sk-admin-"):
        base = "https://api.moonshot.ai/v1/admin/organizations"
        params = {"start": int(_window_start(today).timestamp() * 1000),
                  "end": int(time.time() * 1000), "granularity": "1d", "limit": 1000}
        for page in _pages(get, key, f"{base}/usage/completions", params, "cursor", "next"):
            for row in page["data"]:
                parts = _parts(row.get("prompt_tokens"), row.get("cached_tokens"),
                               row.get("completion_tokens"))
                if sum(parts.values()):
                    add_usage(result["daily"], date.fromisoformat(row["bucket_time"][:10]),
                              row.get("model_id") or "unknown", ACCOUNT_PROJECT, parts)
        account = get(f"{base}/account", key)
        result["rows"] = [
            ["Balance", _money(account["available_balance"] / MILLI_CENTS_PER_DOLLAR, "$")],
            ["Total spent", _money(account["total_consume"] / MILLI_CENTS_PER_DOLLAR, "$")],
        ]
        return result

    # Ordinary API key: balance. Keys from Kimi's China platform only work on
    # the .cn host.
    try:
        data, symbol = get("https://api.moonshot.ai/v1/users/me/balance", key)["data"], "$"
    except urllib.error.HTTPError as e:
        if e.code != 401:
            raise
        data, symbol = get("https://api.moonshot.cn/v1/users/me/balance", key)["data"], "¥"
    result["rows"] = [
        ["Balance", _money(data["available_balance"], symbol)],
        ["Vouchers", _money(data["voucher_balance"], symbol)],
        ["Cash", _money(data["cash_balance"], symbol)],
    ]
    result["notes"].append("An admin key (sk-admin-…) also shows usage history")
    return result


FETCHERS = {"openai": _fetch_openai, "deepseek": _fetch_deepseek, "kimi": _fetch_kimi}


def fetch_account(provider, key, today=None, get=None):
    """{"daily", "cost": {iso: usd}, "rows": [[label, value]], "notes",
    "error", "fetched_at"} for `provider`'s account. Never raises."""
    get = get or (lambda url, k: http_get_json(url, k, provider))
    try:
        result = FETCHERS[provider](key, today or date.today(), get)
    except (OSError, KeyError, TypeError, ValueError, AttributeError) as e:
        result = {**_empty_result(), "error": _describe(e, NAMES[provider])}
    result["fetched_at"] = datetime.now().isoformat(timespec="seconds")
    return result


def store_result(state, provider, result):
    """Save a fetch into state["accounts"]. A failed fetch keeps the last good
    numbers and records the error."""
    accounts = state.setdefault("accounts", {})
    saved = accounts.get(provider, {})
    if result["error"]:
        saved = {**saved, "error": result["error"], "attempted_at": result["fetched_at"]}
    else:
        saved = {**result, "attempted_at": result["fetched_at"]}
    accounts[provider] = saved


def account_due(saved, now=None):
    if not saved or not saved.get("attempted_at"):
        return True
    last = datetime.fromisoformat(saved["attempted_at"])
    return ((now or datetime.now()) - last).total_seconds() >= REFRESH_SECONDS
