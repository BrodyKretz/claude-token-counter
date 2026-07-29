import json
import subprocess
import urllib.error
import urllib.request

KEYCHAIN_SERVICE = "com.claudetokencounter.github"
GIST_FILENAME = "claude-token-leaderboard.json"
API_BASE = "https://api.github.com"
NEW_TOKEN_URL = (
    "https://github.com/settings/tokens/new?scopes=gist"
    "&description=Claude+Token+Counter+Leaderboard"
)


def get_github_token():
    """Read the GitHub token from the macOS Keychain, or None if never set."""
    result = subprocess.run(
        ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def set_github_token(token):
    """Store the GitHub token in the macOS Keychain, overwriting any existing one."""
    subprocess.run(
        [
            "security",
            "add-generic-password",
            "-s",
            KEYCHAIN_SERVICE,
            "-a",
            KEYCHAIN_SERVICE,
            "-w",
            token,
            "-U",
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def _api_request(method, url, token=None, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Accept", "application/vnd.github+json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def create_gist(token, content):
    """Create a new secret Gist holding `content`, returning its ID (the friend code)."""
    payload = {
        "description": "Claude Token Counter leaderboard entry",
        "public": False,
        "files": {GIST_FILENAME: {"content": json.dumps(content)}},
    }
    result = _api_request("POST", f"{API_BASE}/gists", token=token, payload=payload)
    return result["id"]


def update_gist(token, gist_id, content):
    """Overwrite the leaderboard file in an existing Gist you own."""
    payload = {"files": {GIST_FILENAME: {"content": json.dumps(content)}}}
    _api_request("PATCH", f"{API_BASE}/gists/{gist_id}", token=token, payload=payload)


def fetch_gist(gist_id):
    """Read a friend's leaderboard entry. No token needed -- gists are readable by ID."""
    result = _api_request("GET", f"{API_BASE}/gists/{gist_id}")
    raw_content = result["files"][GIST_FILENAME]["content"]
    return json.loads(raw_content)
