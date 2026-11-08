import io
import subprocess
import urllib.error
from datetime import date, datetime
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

import accounts
from accounts import (
    ALLOWED_HOSTS,
    account_due,
    delete_key,
    fetch_account,
    load_key,
    save_key,
    store_result,
    valid_key,
)

TODAY = date(2026, 11, 8)


class FakeApi:
    """Answers GETs by path; records every (host, path, query, key)."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, url, key):
        parsed = urlparse(url)
        self.calls.append((parsed.netloc, parsed.path, parse_qs(parsed.query), key))
        answer = self.routes[(parsed.netloc, parsed.path)]
        if callable(answer):
            answer = answer(parse_qs(parsed.query))
        if isinstance(answer, Exception):
            raise answer
        return answer


def http_error(code):
    return urllib.error.HTTPError("https://x", code, "nope", {}, io.BytesIO(b""))


# --- keys -----------------------------------------------------------------

def test_valid_key():
    assert valid_key("sk-admin-AbC_12.3-xyz")
    assert not valid_key("short")
    assert not valid_key("has space in it")
    assert not valid_key('quote"injection-attempt')
    assert not valid_key("new\nline-injection")


def test_save_key_sends_it_on_stdin_not_argv():
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        if args[:2] == ["security", "find-generic-password"]:
            return SimpleNamespace(returncode=0, stdout="sk-test-1234567890\n")
        return SimpleNamespace(returncode=0, stdout="")

    save_key("deepseek", "sk-test-1234567890", run=run)

    args, kwargs = calls[0]
    assert args == ["security", "-i"]
    assert "sk-test-1234567890" not in " ".join(args)
    assert kwargs["input"] == (
        "add-generic-password -U -s com.raymondtian.claudetracker.apikey "
        "-a deepseek -w sk-test-1234567890\n"
    )


def test_save_key_rejects_invalid_keys_without_running_anything():
    with pytest.raises(ValueError):
        save_key("kimi", "bad key", run=lambda *a, **k: pytest.fail("ran"))


def test_save_key_fails_if_keychain_did_not_store_it():
    run = lambda args, **k: SimpleNamespace(returncode=0 if args[1] == "-i" else 44, stdout="")
    with pytest.raises(OSError):
        save_key("kimi", "sk-test-1234567890", run=run)


def test_load_and_delete_key():
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="sk-abc-1234567890\n")

    assert load_key("openai", run=run) == "sk-abc-1234567890"
    delete_key("openai", run=run)
    assert calls == [
        ["security", "find-generic-password", "-s", "com.raymondtian.claudetracker.apikey",
         "-a", "openai", "-w"],
        ["security", "delete-generic-password", "-s", "com.raymondtian.claudetracker.apikey",
         "-a", "openai"],
    ]


def test_load_key_missing():
    assert load_key("openai", run=lambda *a, **k: SimpleNamespace(returncode=44, stdout="")) is None


# --- OpenAI ---------------------------------------------------------------

def _ts(day):
    return int(datetime(day.year, day.month, day.day).timestamp())


def openai_routes():
    usage_pages = {
        None: {"data": [{"start_time": _ts(date(2026, 11, 7)), "results": [
            {"model": "gpt-5", "input_tokens": 100, "input_cached_tokens": 60, "output_tokens": 9},
        ]}], "has_more": True, "next_page": "p2"},
        "p2": {"data": [{"start_time": _ts(TODAY), "results": [
            {"model": "gpt-5", "input_tokens": 10, "input_cached_tokens": 0, "output_tokens": 1},
            {"model": None, "input_tokens": 4, "output_tokens": 0},
        ]}], "has_more": False, "next_page": None},
    }
    costs = {"data": [
        {"start_time": _ts(date(2026, 11, 7)), "results": [{"amount": {"value": 1.25, "currency": "usd"}}]},
        {"start_time": _ts(TODAY), "results": [{"amount": {"value": 0.5, "currency": "usd"}},
                                               {"amount": {"value": 0.25, "currency": "usd"}}]},
    ], "has_more": False, "next_page": None}
    return {
        ("api.openai.com", "/v1/organization/usage/completions"):
            lambda q: usage_pages[q.get("page", [None])[0]],
        ("api.openai.com", "/v1/organization/costs"): costs,
    }


def test_openai_admin_key_gives_daily_tokens_and_billed_cost():
    api = FakeApi(openai_routes())

    result = fetch_account("openai", "sk-admin-1234567890", today=TODAY, get=api)

    assert result["error"] is None
    nov7 = result["daily"]["2026-11-07"]["models"]["gpt-5"]
    assert (nov7["input"], nov7["cache_read"], nov7["output"]) == (40, 60, 9)
    assert result["daily"]["2026-11-08"]["models"]["unknown"]["input"] == 4
    assert result["cost"] == {"2026-11-07": 1.25, "2026-11-08": 0.75}
    usage_call = api.calls[0]
    assert usage_call[2]["bucket_width"] == ["1d"]
    assert usage_call[2]["group_by"] == ["model"]
    assert usage_call[2]["start_time"] == [str(_ts(date(2026, 10, 10)))]


def test_openai_needs_an_admin_key_and_sends_nothing_otherwise():
    api = FakeApi({})

    result = fetch_account("openai", "sk-proj-1234567890", today=TODAY, get=api)

    assert "admin key" in result["error"]
    assert api.calls == []


def test_openai_cost_failure_keeps_usage():
    routes = openai_routes()
    routes[("api.openai.com", "/v1/organization/costs")] = http_error(404)

    result = fetch_account("openai", "sk-admin-1234567890", today=TODAY, get=FakeApi(routes))

    assert result["error"] is None
    assert result["daily"]
    assert result["cost"] == {}
    assert any("cost" in n.lower() for n in result["notes"])


# --- DeepSeek -------------------------------------------------------------

def test_deepseek_balance():
    api = FakeApi({("api.deepseek.com", "/user/balance"): {
        "is_available": False,
        "balance_infos": [{"currency": "CNY", "total_balance": "110.00",
                           "granted_balance": "10.00", "topped_up_balance": "100.00"}],
    }})

    result = fetch_account("deepseek", "sk-1234567890", today=TODAY, get=api)

    assert result["error"] is None
    assert result["daily"] == {}
    assert result["rows"] == [["Balance", "¥110.00"], ["Granted", "¥10.00"], ["Topped up", "¥100.00"]]
    assert result["notes"] == ["Balance too low for API calls",
                               "DeepSeek's API reports balance only, not usage history"]


# --- Kimi -----------------------------------------------------------------

def test_kimi_api_key_balance():
    api = FakeApi({("api.moonshot.ai", "/v1/users/me/balance"): {
        "code": 0, "data": {"available_balance": 49.58894, "voucher_balance": 46.58893,
                            "cash_balance": 3.00001}, "status": True,
    }})

    result = fetch_account("kimi", "sk-1234567890", today=TODAY, get=api)

    assert result["rows"] == [["Balance", "$49.59"], ["Vouchers", "$46.59"], ["Cash", "$3.00"]]
    assert result["daily"] == {}


def test_kimi_china_key_falls_back_to_the_cn_host():
    api = FakeApi({
        ("api.moonshot.ai", "/v1/users/me/balance"): http_error(401),
        ("api.moonshot.cn", "/v1/users/me/balance"): {
            "code": 0, "data": {"available_balance": 10, "voucher_balance": 0, "cash_balance": 10}},
    })

    result = fetch_account("kimi", "sk-1234567890", today=TODAY, get=api)

    assert result["error"] is None
    assert result["rows"][0] == ["Balance", "¥10.00"]


def test_kimi_admin_key_gives_usage_and_spend():
    pages = {
        None: {"data": [
            {"bucket_time": "2026-11-07T00:00:00Z", "model_id": "kimi-k2", "prompt_tokens": 50,
             "completion_tokens": 5, "cached_tokens": 20},
            {"bucket_time": "2026-11-07T00:00:00Z", "model_id": "kimi-k2", "prompt_tokens": 10,
             "completion_tokens": 1, "cached_tokens": 0},
        ], "has_more": True, "next": "c2"},
        "c2": {"data": [{"bucket_time": "2026-11-08T00:00:00Z", "model_id": "kimi-k2",
                         "prompt_tokens": 3, "completion_tokens": 2, "cached_tokens": 0}],
               "has_more": False, "next": None},
    }
    api = FakeApi({
        ("api.moonshot.ai", "/v1/admin/organizations/usage/completions"):
            lambda q: pages[q.get("cursor", [None])[0]],
        ("api.moonshot.ai", "/v1/admin/organizations/account"): {
            "available_balance": 4_958_894, "total_consume": 1_250_000,
            "total_recharge_amount": 0, "total_voucher_amount": 0},
    })

    result = fetch_account("kimi", "sk-admin-1234567890", today=TODAY, get=api)

    nov7 = result["daily"]["2026-11-07"]["models"]["kimi-k2"]
    assert (nov7["input"], nov7["cache_read"], nov7["output"]) == (40, 20, 6)
    assert result["rows"] == [["Balance", "$49.59"], ["Total spent", "$12.50"]]
    query = api.calls[0][2]
    assert query["granularity"] == ["1d"]


# --- errors and safety ----------------------------------------------------

def test_rejected_key_reports_an_error_without_the_key():
    api = FakeApi({("api.deepseek.com", "/user/balance"): http_error(401)})

    result = fetch_account("deepseek", "sk-secret-1234567890", today=TODAY, get=api)

    assert result["error"] == "the API key was rejected (HTTP 401)"
    assert "sk-secret" not in repr(result)


def test_unexpected_response_is_an_error():
    api = FakeApi({("api.deepseek.com", "/user/balance"): {"weird": True}})

    assert fetch_account("deepseek", "sk-1234567890", get=api)["error"] == \
        "DeepSeek sent an unexpected response"


def test_keys_only_go_to_the_providers_own_hosts():
    assert ALLOWED_HOSTS == {
        "openai": {"api.openai.com"},
        "deepseek": {"api.deepseek.com"},
        "kimi": {"api.moonshot.ai", "api.moonshot.cn"},
    }
    with pytest.raises(ValueError):
        accounts.http_get_json("https://evil.example.com/x", "sk-1234567890", provider="openai")
    with pytest.raises(ValueError):
        accounts.http_get_json("http://api.openai.com/x", "sk-1234567890", provider="openai")


def test_store_result_keeps_last_good_numbers_on_error():
    state = {}
    store_result(state, "kimi", {"daily": {"d": 1}, "cost": {}, "rows": [["Balance", "$1.00"]],
                                 "notes": [], "error": None, "fetched_at": "t1"})
    store_result(state, "kimi", {"daily": {}, "cost": {}, "rows": [], "notes": [],
                                 "error": "boom", "fetched_at": "t2"})

    saved = state["accounts"]["kimi"]
    assert saved["rows"] == [["Balance", "$1.00"]]
    assert saved["daily"] == {"d": 1}
    assert saved["error"] == "boom"
    assert saved["attempted_at"] == "t2"


def test_account_due():
    now = datetime(2026, 11, 8, 12, 0, 0)
    assert account_due(None, now)
    assert account_due({"attempted_at": "2026-11-08T11:44:00"}, now)
    assert not account_due({"attempted_at": "2026-11-08T11:50:00"}, now)
