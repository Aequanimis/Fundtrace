from tools import runtime_port_guard as guard


def fundtrace_process():
    return {
        "ProcessId": 1234,
        "ExecutablePath": r"C:\FundTrace_Windows_Portable\runtime\python.exe",
        "CommandLine": '"python.exe" -m api.server',
    }


def test_classifies_a_matching_runtime_for_reuse():
    assert guard.classify_runtime(
        "1ccbb8f",
        {"status": "ok", "app": "FundTrace", "git_commit": "1ccbb8f"},
        [fundtrace_process()],
    ) == "CURRENT_RUNTIME_REUSED"


def test_matching_health_identity_can_reuse_a_venv_python_process():
    venv_python = {"ProcessId": 1234, "ExecutablePath": r"D:\ANA\python.exe", "CommandLine": '"python.exe" -m api.server'}
    assert guard.classify_runtime(
        "1ccbb8f",
        {"status": "ok", "app": "FundTrace", "git_commit": "1ccbb8f"},
        [venv_python],
    ) == "CURRENT_RUNTIME_REUSED"


def test_mismatched_fundtrace_identity_is_stale_even_for_a_venv_python_process():
    venv_python = {"ProcessId": 1234, "ExecutablePath": r"D:\ANA\python.exe", "CommandLine": '"python.exe" -m api.server'}
    assert guard.classify_runtime(
        "new-build",
        {"status": "ok", "app": "FundTrace", "git_commit": "old-build"},
        [venv_python],
    ) == "STALE_BACKEND_PROCESS"


def test_classifies_legacy_fundtrace_as_stale():
    assert guard.classify_runtime(
        "1ccbb8f",
        {"status": "ok", "host": "127.0.0.1"},
        [fundtrace_process()],
    ) == "STALE_BACKEND_PROCESS"


def test_never_classifies_unknown_process_as_stale_fundtrace():
    unknown = {"ProcessId": 9, "ExecutablePath": r"C:\Tools\python.exe", "CommandLine": "python app.py"}
    assert guard.classify_runtime("1ccbb8f", None, [unknown]) == "PORT_8765_OCCUPIED_BY_OTHER_APP"
