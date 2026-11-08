import os
import plistlib
import subprocess
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


def test_launcher_runs_app_py_from_the_project(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    (project / "app.py").write_text("import os; open('ran.txt', 'w').write(os.getcwd())\n")

    bundle = build_app.build(tmp_path, "/usr/bin/python3", project_dir=project, icon=False)
    subprocess.run([str(bundle / "Contents" / "MacOS" / build_app.EXECUTABLE_NAME)], check=True)

    assert Path((project / "ran.txt").read_text()).resolve() == project.resolve()


def test_build_replaces_existing_bundle_and_makes_icon(tmp_path):
    stale = tmp_path / f"{APP_NAME}.app" / "Contents" / "stale.txt"
    stale.parent.mkdir(parents=True)
    stale.write_text("old")

    bundle = build_app.build(tmp_path, "/usr/bin/python3", project_dir=tmp_path)

    assert not stale.exists()
    icon = bundle / "Contents" / "Resources" / f"{build_app.ICON_NAME}.icns"
    assert icon.stat().st_size > 10_000
