import sys

import pytest

from bootstrap import StartupLog, compatible_python, prepare_environment, python_path, run_logged


def test_supported_python_versions_and_architecture():
    for version in [(3, 11), (3, 12), (3, 13)]:
        assert compatible_python(version, 64)
    for version in [(3, 10), (3, 14), (4, 0)]:
        assert not compatible_python(version, 64)
    assert not compatible_python((3, 11), 32)


def test_child_errors_remain_in_log_and_exit_status_is_preserved(tmp_path):
    log = StartupLog(tmp_path / "logs/startup.log")
    status = run_logged([sys.executable, "-c", "import sys; print('missing library', file=sys.stderr); sys.exit(7)"],
                        tmp_path, log)
    log.close()
    assert status == 7
    assert "missing library" in (tmp_path / "logs/startup.log").read_text("utf-8")


def test_partial_install_is_retried_on_the_next_launch(tmp_path):
    (tmp_path / "requirements.txt").write_text("Pillow==11.2.1\n")
    interpreter = python_path(tmp_path / ".venv-win")
    interpreter.parent.mkdir(parents=True)
    interpreter.touch()
    log = StartupLog(tmp_path / "startup.log")
    installs = []
    repaired = False
    def fake_run(command, root, output):
        nonlocal repaired
        if "-c" in command and "import importlib.metadata" in command[-1]:
            return 0 if repaired else 1
        if "install" in command:
            installs.append(command)
            if len(installs) == 1:
                return 1
            repaired = True
        return 0
    with pytest.raises(RuntimeError, match="Установка"):
        prepare_environment(tmp_path, log, fake_run)
    assert interpreter.is_file()
    assert prepare_environment(tmp_path, log, fake_run) == interpreter
    assert len(installs) == 2
    assert prepare_environment(tmp_path, log, fake_run) == interpreter
    assert len(installs) == 2
    log.close()
