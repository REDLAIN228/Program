"""Build with the exact interpreter selected by the source launcher."""
import os
import sys


def build_application(root, interpreter, log, run):
    if sys.platform != "win32":
        raise RuntimeError("Windows EXE must be built on Windows.")
    commands = [
        [str(interpreter), "-m", "pip", "install", "-r", str(root / "requirements-dev.txt")],
        [str(interpreter), "-m", "pytest", "-q"],
        [str(interpreter), "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--onedir",
         "--name", "AnimeDrawer", "--icon", str(root / "assets/anime-drawer.ico"),
         "--collect-all", "mss", "--collect-all", "keyring",
         "--hidden-import", "keyring.backends.Windows", str(root / "main.py")],
    ]
    for index, command in enumerate(commands):
        if index == 1:
            previous = os.environ.get("QT_QPA_PLATFORM")
            try:
                os.environ["QT_QPA_PLATFORM"] = "offscreen"
                status = run(command, root, log)
            finally:
                if previous is None:
                    os.environ.pop("QT_QPA_PLATFORM", None)
                else:
                    os.environ["QT_QPA_PLATFORM"] = previous
        else:
            status = run(command, root, log)
        if status:
            log.write("Build failed; see the command output above.")
            return 1
    log.write(f"Build complete: {root / 'dist/AnimeDrawer/AnimeDrawer.exe'}")
    log.write("Distribute the complete dist/AnimeDrawer folder, including _internal.")
    return 0
