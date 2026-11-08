import os
import plistlib
import subprocess
import time
from pathlib import Path

import build_app
from version import APP_NAME, __version__


def test_build_creates_menu_bar_only_bundle(tmp_path):
    project = tmp_path / "my project"  # a space, to check quoting
    project.mkdir()

    bundle = build_app.build(tmp_path / "Apps", "/usr/bin/python3", project_dir=project, icon=False)

    assert bundle == tmp_path / "Apps" / f"{APP_NAME}.app"
    with open(bundle / "Contents" / "Info.plist", "rb") as f:
        info = plistlib.load(f)
    assert info["CFBundleExecutable"] == build_app.EXECUTABLE_NAME
    assert info["CFBundleShortVersionString"] == __version__
    assert info["LSUIElement"] is True
    executable = bundle / "Contents" / "MacOS" / build_app.EXECUTABLE_NAME
    assert os.access(executable, os.X_OK)
    script = executable.read_text()
    assert f"cd '{project}'" in script
    assert f"exec /usr/bin/python3 '{project / 'app.py'}'" in script
    assert f"nohup /usr/bin/python3 '{project / 'app.py'}'" in script


def _fake_project(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    # Records its working directory and parent pid, then exits.
    (project / "app.py").write_text(
        "import os; open('ran.txt', 'w').write(os.getcwd() + '\\n' + str(os.getppid()))\n"
    )
    bundle = build_app.build(tmp_path, "/usr/bin/python3", project_dir=project, icon=False)
    return project, bundle / "Contents" / "MacOS" / build_app.EXECUTABLE_NAME


def _wait_for(path, seconds=5):
    deadline = time.monotonic() + seconds
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    return path.read_text().split("\n")


def test_launcher_foreground_runs_app_in_its_own_process(tmp_path):
    project, launcher = _fake_project(tmp_path)

    launcher_proc = subprocess.Popen([str(launcher), "--foreground"])
    launcher_proc.wait(timeout=5)
    cwd, parent = _wait_for(project / "ran.txt")

    assert Path(cwd).resolve() == project.resolve()
    # exec: app.py replaced the launcher, so its parent is this test.
    assert int(parent) == os.getpid()


def test_launcher_from_finder_starts_app_in_background_and_exits(tmp_path):
    project, launcher = _fake_project(tmp_path)

    result = subprocess.run([str(launcher)], timeout=5)
    cwd, parent = _wait_for(project / "ran.txt")

    assert result.returncode == 0
    assert Path(cwd).resolve() == project.resolve()
    assert int(parent) != os.getpid()


def test_build_replaces_existing_bundle_and_makes_icon(tmp_path):
    stale = tmp_path / f"{APP_NAME}.app" / "Contents" / "stale.txt"
    stale.parent.mkdir(parents=True)
    stale.write_text("old")

    bundle = build_app.build(tmp_path, "/usr/bin/python3", project_dir=tmp_path)

    assert not stale.exists()
    icon = bundle / "Contents" / "Resources" / f"{build_app.ICON_NAME}.icns"
    assert icon.stat().st_size > 10_000
