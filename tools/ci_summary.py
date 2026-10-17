"""Publish bounded pytest diagnostics to the workflow summary, preserving test status in CI."""
from pathlib import Path
import sys


def main():
    source, destination = map(Path, sys.argv[1:3])
    log = (source.read_text(encoding="utf-8-sig", errors="replace") if source.exists()
           else "No pytest log was produced; inspect the preceding setup/test step.")
    # Test output only: never inspect credentials or the process environment.
    log = log[-60_000:].replace("```", "~~~")
    with destination.open("a", encoding="utf-8") as output:
        output.write("\n### Windows headless test results\n\n```text\n" + log + "\n```\n")


if __name__ == "__main__":
    main()
