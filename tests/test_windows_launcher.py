from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BAT = (ROOT / "启动FundTrace.bat").read_text(encoding="utf-8")


def test_launcher_requires_explicit_python_312() -> None:
    assert "py -3.12 --version" in BAT
    assert "py -3 -m venv" not in BAT
    assert "Python 3.12.x was not found" in BAT


def test_launcher_handles_only_project_broken_venv() -> None:
    removals = [line.strip() for line in BAT.splitlines() if "rmdir " in line.lower()]
    assert removals == [
        'rmdir /s /q "%CD%\\.venv"',
        'rmdir /s /q "%CD%\\.venv"',
    ]


def test_launcher_uses_lock_and_skips_install_when_verified() -> None:
    assert 'tools\\check_locked_environment.py' in BAT
    assert '-m pip install -r "requirements-lock.txt"' in BAT
    assert "pip install -U" not in BAT


def test_launcher_has_utf8_log_and_local_service_guard() -> None:
    assert 'set "STARTUP_LOG=%LOG_DIR%\\startup.log"' in BAT
    assert "tools\\run_server_logged.py" in BAT
    assert "host=127.0.0.1; port=8765" in BAT
