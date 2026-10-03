#!/usr/bin/env python3
"""Overlay-fork guard.

The fork may only modify upstream (CloakHQ/CloakBrowser) files registered in
metabrowser/seams.txt, each within its changed-line budget (-1 = fork-owned new file).
Small, registered, append-style seams keep `git merge upstream/main` conflict-free;
git rerere replays any resolution that was needed once.

    python3 metabrowser/scripts/fork_guard.py [upstream-ref]
"""

import subprocess
import sys
from pathlib import Path


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout.strip()


def main() -> int:
    ref = sys.argv[1] if len(sys.argv) > 1 else "upstream/main"
    root = Path(git("rev-parse", "--show-toplevel"))
    budget: dict[str, int] = {}
    for line in (root / "metabrowser" / "seams.txt").read_text().splitlines():
        parts = line.split()
        if parts and not parts[0].startswith("#"):
            budget[parts[0]] = int(parts[1])
    base = git("merge-base", ref, "HEAD")
    problems = []
    for row in git("diff", "--numstat", base, "HEAD").splitlines():
        added, removed, path = row.split("\t", 2)
        if path.startswith("metabrowser/"):
            continue
        if path not in budget:
            problems.append(f"unregistered upstream change: {path} (+{added}/-{removed})")
            continue
        changed = (int(added) if added.isdigit() else 0) + (int(removed) if removed.isdigit() else 0)
        if budget[path] != -1 and changed > budget[path]:
            problems.append(f"seam {path} changed {changed} lines, budget {budget[path]}")
    if problems:
        print("fork-guard:\n  " + "\n  ".join(problems), file=sys.stderr)
        print("Move the change under metabrowser/, upstream it to CloakHQ/CloakBrowser, "
              "or register a small append-only seam in metabrowser/seams.txt.", file=sys.stderr)
        return 1
    print(f"fork-guard: ok (base {base[:7]}, {len(budget)} registered seams)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
