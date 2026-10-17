"""Windows regression: dependencies stay short even inside nested GitHub ZIP folders."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main():
    if sys.platform != "win32":
        raise SystemExit("This regression check runs on Windows")
    root = Path(__file__).resolve().parents[1]
    expected = Path((root / "logs/python-path.txt").read_text("utf-8").strip())
    folder = "Program-0c7ace8ad134b74d7a89ada162fd627da5c25b3d"
    with tempfile.TemporaryDirectory(prefix="ad-path-") as directory:
        copied = Path(directory) / folder / folder
        shutil.copytree(root, copied, ignore=shutil.ignore_patterns(
            ".git", ".venv", ".venv-win", "logs", "artifacts", "build", "dist", "__pycache__", ".pytest_cache"))
        subprocess.run(["cmd", "/d", "/c", "run.bat", "--install-only"], cwd=copied, check=True)
        actual = Path((copied / "logs/python-path.txt").read_text("utf-8").strip())
        assert actual == expected, "The same pinned dependencies should reuse one short environment"
        assert not actual.is_relative_to(copied)
        relative = Path("Lib/site-packages/PySide6/qml/QtQuick/Controls/FluentWinUI3/dark/images/"
                        "editablecombobox-popup-background-hovered-open@2x.png")
        assert len(str(actual.parent.parent / relative)) < 260
        print("Nested GitHub archive startup: OK; Qt installation path is below MAX_PATH")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
