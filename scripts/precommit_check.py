#!/usr/bin/env python
"""Pre-commit sanity gate for staged Python files.

Catches the class of bug that keeps recurring in this repo: code that
*compiles* but crashes at runtime on an undefined name (missing import),
plus outright SyntaxErrors. Run automatically by .git/hooks/pre-commit;
can also be run manually:  python scripts/precommit_check.py file1.py ...
"""
import py_compile
import subprocess
import sys


def staged_python_files():
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True, text=True,
    ).stdout
    return [f for f in out.splitlines() if f.endswith(".py")]


def main(argv):
    raw = argv[1:] or staged_python_files()
    # In staged mode the helper already filters to *.py. In explicit-argv
    # mode (e.g. `python scripts/precommit_check.py README.md ...`) we
    # must do the same ourselves — otherwise py_compile chokes on a UTF-8
    # em-dash in a Markdown file and we get a spurious SyntaxError.
    files = [f for f in raw if f.endswith(".py")]
    if not files:
        return 0

    failed = False

    # 1. Compile each file — catches SyntaxError / IndentationError.
    for f in files:
        try:
            py_compile.compile(f, doraise=True)
        except py_compile.PyCompileError as exc:
            print(f"[precommit] SYNTAX ERROR in {f}:\n{exc}")
            failed = True

    # 2. pyflakes — catches undefined names (missing imports). Optional:
    #    skip silently if pyflakes isn't installed so the hook never blocks
    #    purely for lack of a dev dependency.
    try:
        res = subprocess.run(
            [sys.executable, "-m", "pyflakes", *files],
            capture_output=True, text=True,
        )
        for line in res.stdout.splitlines():
            if "undefined name" in line:
                print(f"[precommit] {line}")
                failed = True
    except Exception:
        pass

    if failed:
        print("\n[precommit] Commit blocked. Fix the errors above "
              "(or `git commit --no-verify` to override).")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
