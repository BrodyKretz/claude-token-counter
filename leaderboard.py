import json
from pathlib import Path

FRIENDS_FILE = Path(__file__).resolve().parent / "friends.json"


def load_friends(friends_file=FRIENDS_FILE):
    """BETA: friend syncing isn't implemented yet -- this just reads a local
    JSON file of {"name", "total_tokens", "yesterday_tokens"} entries that
    something else will need to populate later.
    """
    if friends_file.exists():
        return json.loads(friends_file.read_text())
    return []


def save_friends(friends, friends_file=FRIENDS_FILE):
    friends_file.write_text(json.dumps(friends))


def sorted_friends(friends, by="total"):
    """`by` is "total" or "day" -- sorts highest usage first."""
    key = "total_tokens" if by == "total" else "yesterday_tokens"
    return sorted(friends, key=lambda f: f.get(key, 0), reverse=True)
