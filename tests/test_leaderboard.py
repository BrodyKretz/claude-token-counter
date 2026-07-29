import json

from leaderboard import load_friends, save_friends, sorted_friends


def test_load_friends_returns_empty_list_when_file_missing(tmp_path):
    assert load_friends(tmp_path / "friends.json") == []


def test_save_then_load_friends_round_trips(tmp_path):
    friends_file = tmp_path / "friends.json"
    friends = [{"name": "Alice", "total_tokens": 10, "yesterday_tokens": 1}]

    save_friends(friends, friends_file)

    assert load_friends(friends_file) == friends
    assert json.loads(friends_file.read_text()) == friends


def test_sorted_friends_by_total_descending():
    friends = [
        {"name": "Alice", "total_tokens": 10, "yesterday_tokens": 100},
        {"name": "Bob", "total_tokens": 50, "yesterday_tokens": 1},
    ]

    result = sorted_friends(friends, by="total")

    assert [f["name"] for f in result] == ["Bob", "Alice"]


def test_sorted_friends_by_day_descending():
    friends = [
        {"name": "Alice", "total_tokens": 10, "yesterday_tokens": 100},
        {"name": "Bob", "total_tokens": 50, "yesterday_tokens": 1},
    ]

    result = sorted_friends(friends, by="day")

    assert [f["name"] for f in result] == ["Alice", "Bob"]


def test_sorted_friends_missing_metric_defaults_to_zero():
    friends = [{"name": "Alice"}, {"name": "Bob", "total_tokens": 5}]

    result = sorted_friends(friends, by="total")

    assert [f["name"] for f in result] == ["Bob", "Alice"]
