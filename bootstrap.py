"""Source launcher: diagnose Python, repair partial installs, retain startup errors.

Only uses the standard library. run.bat tries this before importing any GUI library.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import os
from pathlib import Path
import struct
import subprocess
import sys
import traceback


def compatible_python(version=None, pointer_bits=None):
    version = sys.version_info[:2] if version is None else version
    pointer_bits = struct.calcsize("P") * 8 if pointer_bits is None else pointer_bits
    return (3, 11) <= tuple(version) < (3, 14) and pointer_bits == 64


class StartupLog:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.file = path.open("a", encoding="utf-8")
        self.write("\n--- ANIME DRAWER startup " + datetime.now().isoformat(timespec="seconds") + " ---")

    def write(self, message):
        self.file.write(message + "\n")
        self.file.flush()
        try:
            print(message, flush=True)
        except UnicodeEncodeError:
            print(message.encode("ascii", errors="backslashreplace").decode("ascii"), flush=True)

    def close(self):
        self.file.close()


def run_logged(command, root, log):
    """Preserve the subprocess exit code while streaming to console and a UTF-8 log."""
    process = subprocess.Popen(command, cwd=root, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    for line in process.stdout:
        log.write(line.rstrip("\r\n"))
    process.stdout.close()
    return process.wait()


def python_path(environment):
    return environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def environment_path(root, platform=None, local_appdata=None):
    platform = sys.platform if platform is None else platform
    if platform != "win32":
        return root / ".venv-win"
    local_appdata = os.environ.get("LOCALAPPDATA") if local_appdata is None else local_appdata
    if not local_appdata:
        raise RuntimeError("Windows не предоставила LOCALAPPDATA для установки библиотек.")
    # GitHub ZIP folders contain a 40-character SHA and may be nested twice.
    # Qt ships long QML filenames; keep dependencies outside that project path.
    digest = hashlib.sha256((root / "requirements.txt").read_bytes()).hexdigest()[:10]
    version = f"py{sys.version_info.major}{sys.version_info.minor}"
    return Path(local_appdata) / "AD" / "envs" / f"{version}-{digest}"


def dependency_probe(root):
    requirements = []
    for line in (root / "requirements.txt").read_text("utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            name, version = line.split("==", 1)
            requirements.append((name.strip(), version.strip()))
    return ("import importlib.metadata as m,sys\n"
            f"wanted={requirements!r}\n"
            "wrong=[]\n"
            "for name,version in wanted:\n"
            "    try:\n"
            "        if m.version(name)!=version: wrong.append(name)\n"
            "    except m.PackageNotFoundError: wrong.append(name)\n"
            "if wrong:\n"
            "    print('Missing or incompatible packages: '+', '.join(wrong))\n"
            "    sys.exit(1)\n"
            "try:\n"
            "    from PySide6 import QtCore, QtWidgets\n"
            "    import cv2,PIL,numpy,mss,httpx,keyring\n"
            "except Exception as error:\n"
            "    print('Library import failed: '+str(error))\n"
            "    sys.exit(1)\n"
            "print('Runtime dependencies: OK')\n")


def prepare_environment(root, log, run=run_logged, environment=None):
    environment = environment if environment is not None else environment_path(root)
    log.write(f"Окружение Python: {environment}")
    interpreter = python_path(environment)
    if not interpreter.is_file():
        log.write("Создаю окружение Python…")
        if run([sys.executable, "-m", "venv", str(environment)], root, log):
            raise RuntimeError("Не удалось создать окружение. Подробности выше в журнале.")
    if not interpreter.is_file():
        raise RuntimeError("Python окружения не появился после установки.")
    check = ("import sys,struct; "
             "sys.exit(0 if (3,11)<=sys.version_info[:2]<(3,14) and struct.calcsize('P')==8 else 1)")
    if run([str(interpreter), "-c", check], root, log):
        raise RuntimeError(f"Окружение использует неподходящий Python: {environment}. "
                           "Переименуйте указанную папку и запустите run.bat снова.")
    probe = [str(interpreter), "-X", "utf8", "-c", dependency_probe(root)]
    if run(probe, root, log) == 0:
        return interpreter
    log.write("Устанавливаю или восстанавливаю библиотеки. Нужен интернет; дождитесь завершения…")
    if run([str(interpreter), "-m", "pip", "--version"], root, log):
        if run([str(interpreter), "-m", "ensurepip", "--upgrade"], root, log):
            raise RuntimeError("Не удалось восстановить pip.")
    install = [str(interpreter), "-m", "pip", "install", "--disable-pip-version-check",
               "-r", str(root / "requirements.txt")]
    if run(install, root, log):
        raise RuntimeError("Установка библиотек не завершилась. Точная причина указана выше в журнале. "
                           "Следующий запуск снова попробует установить зависимости.")
    if run(probe, root, log):
        raise RuntimeError("Библиотеки установлены, но не загружаются. "
                           "На Windows проверьте Microsoft Visual C++ Redistributable x64. "
                           "Точная ошибка загрузки указана выше.")
    return interpreter


def main(argv=None):
    parser = argparse.ArgumentParser(description="ANIME DRAWER startup and dependency repair")
    parser.add_argument("--check-python", action="store_true")
    parser.add_argument("--install-only", action="store_true")
    parser.add_argument("--build", action="store_true")
    args, app_args = parser.parse_known_args(argv)
    if args.check_python:
        return 0 if compatible_python() else 1
    if not compatible_python():
        print("Required: 64-bit Python 3.11, 3.12 or 3.13. Python 3.14+ is not supported.")
        return 1
    root = Path(__file__).resolve().parent
    try:
        log = StartupLog(root / "logs/startup.log")
    except OSError as exc:
        print("Cannot write logs/startup.log. Extract the project to a writable folder.\n" + str(exc))
        return 1
    try:
        if not (root / "main.py").is_file() or not (root / "app").is_dir():
            raise RuntimeError("Распакуйте архив целиком: рядом нужны main.py, requirements.txt и app.")
        interpreter = prepare_environment(root, log)
        (log.path.parent / "python-path.txt").write_text(str(interpreter), encoding="utf-8")
        if args.build:
            from tools.windows_build import build_application
            return build_application(root, interpreter, log, run_logged)
        if args.install_only:
            log.write("Окружение готово. Для запуска откройте run.bat.")
            return 0
        log.write("Запускаю окно ANIME DRAWER…")
        result = run_logged([str(interpreter), "-X", "utf8", "-X", "faulthandler", "-u",
                             str(root / "main.py"), *app_args], root, log)
        if result:
            log.write(f"Программа завершилась с ошибкой {result}. Журнал: {log.path}")
            return 1
        return 0
    except Exception:
        log.write(traceback.format_exc())
        return 1
    finally:
        log.close()


if __name__ == "__main__":
    raise SystemExit(main())
