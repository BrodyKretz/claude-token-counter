import subprocess
from collections import Counter
from pathlib import Path

from token_math import CLAUDE_PROJECTS_DIR, sum_usage_since


def running_claude_cwds():
    """Return the working directory (str) of each currently running `claude` CLI
    process, one entry per process (duplicates if several share a directory).
    """
    ps_output = subprocess.run(
        ["ps", "-eo", "pid,comm"], capture_output=True, text=True, check=True
    ).stdout

    pids = []
    for line in ps_output.splitlines()[1:]:
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        pid, comm = parts
        if comm.strip() == "claude":
            pids.append(pid.strip())

    cwds = []
    for pid in pids:
        result = subprocess.run(
            ["lsof", "-a", "-p", pid, "-d", "cwd", "-Fn"],
            capture_output=True,
            text=True,
        )
        for line in result.stdout.splitlines():
            if line.startswith("n"):
                cwds.append(line[1:])
    return cwds


def project_dir_for_cwd(cwd, projects_dir=CLAUDE_PROJECTS_DIR):
    return projects_dir / cwd.replace("/", "-")


def display_name(cwd, home=None):
    home = str(home or Path.home())
    if cwd == home:
        return "~"
    if cwd.startswith(home + "/"):
        return "~/" + cwd[len(home) + 1 :]
    return cwd


def active_sessions(projects_dir=CLAUDE_PROJECTS_DIR, cwds=None):
    """Best-effort list of currently running Claude Code terminals.

    Each running `claude` process is matched to the most-recently-modified
    session file in its project directory (the CLI doesn't expose which exact
    file belongs to which pid). When several processes share a directory, the
    top-N most recently modified files there are used, N being how many
    processes share it.

    Returns a list of {"label": str, "tokens": int}, most tokens first.
    """
    cwds = running_claude_cwds() if cwds is None else cwds
    cwd_counts = Counter(cwds)

    sessions = []
    for cwd, count in cwd_counts.items():
        project_dir = project_dir_for_cwd(cwd, projects_dir)
        if not project_dir.is_dir():
            continue
        files = sorted(
            project_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True
        )
        for path in files[:count]:
            tokens, _ = sum_usage_since(path, 0)
            sessions.append({"label": display_name(cwd), "tokens": tokens})

    sessions.sort(key=lambda s: s["tokens"], reverse=True)
    return sessions
