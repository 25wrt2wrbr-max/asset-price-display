#!/usr/bin/env python3
"""Scan the project for this machine's account name before anything is published.

    python3 check_publish.py            # the working tree (skips .cache, .git, caches)
    python3 check_publish.py --history  # also every commit, if this is a git repo

The name is read from the running account at run time and is never written in
this file, so the check cannot itself leak what it looks for. It reports
file:line only and never prints the matching text. Exit status 1 means "found";
do not publish until it is 0 (rewrite history if the hits are in old commits).
"""

import getpass
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent
SKIP_DIRS = {".git", ".cache", "__pycache__"}


def needles() -> list[bytes]:
    names = {getpass.getuser(), pathlib.Path.home().name}
    names.discard("")
    return sorted({n.encode() for n in names} | {n.lower().encode() for n in names})


def scan_tree(needle_list: list[bytes]) -> list[str]:
    hits = []
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            path = pathlib.Path(base) / name
            try:
                data = path.read_bytes()      # binaries too: build paths land in them
            except OSError:
                continue
            low = data.lower()
            for needle in needle_list:
                if needle.lower() in low:
                    line = low[:low.index(needle.lower())].count(b"\n") + 1
                    hits.append("%s:%d" % (path.relative_to(ROOT), line))
                    break
    return hits


def scan_history(needle_list: list[bytes]) -> list[str]:
    if not (ROOT / ".git").exists():
        return []
    log = subprocess.run(["git", "log", "--all", "-p", "--format=commit %H"],
                         cwd=ROOT, capture_output=True).stdout
    commit, hits = "", []
    for raw in log.split(b"\n"):
        if raw.startswith(b"commit "):
            commit = raw[7:19].decode()
        elif any(n.lower() in raw.lower() for n in needle_list):
            hits.append("history: commit %s" % commit)
    return sorted(set(hits))


def main() -> int:
    found = needles()
    hits = scan_tree(found)
    if "--history" in sys.argv:
        hits += scan_history(found)
    for hit in hits:
        print(hit)
    print("%d hit(s)" % len(hits))
    return 1 if hits else 0


if __name__ == "__main__":
    raise SystemExit(main())
