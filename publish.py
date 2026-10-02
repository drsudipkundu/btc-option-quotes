r"""
publish.py -- commit the files a collector run produced and push them, safely alongside other runs.

Collectors write into a scratch folder (_out/) instead of the repo itself. This script then, up to 6 times:
    1. git fetch + reset to the newest origin/main   (= "git pull --rebase", but conflicts are impossible)
    2. copies the new snapshot files into data/ and APPENDS new missing.csv rows to the existing ones
    3. commits and pushes; if another workflow pushed in between, the push is rejected -> start again
So the evening loop and the half-hourly snapshot can finish at the same moment without losing anything.

    python publish.py _out "evening 2026-10-02"
"""
import os
import shutil
import subprocess
import sys
import time


def git(*args, check=True):
    print("+ git", " ".join(args), flush=True)
    return subprocess.run(["git", *args], check=check)


def merge_into_repo(src):
    """Copy src/data/** into ./data/**. missing.csv: append rows (minus header) instead of overwriting."""
    n = 0
    for root, _, files in os.walk(os.path.join(src, "data")):
        rel = os.path.relpath(root, src)
        os.makedirs(rel, exist_ok=True)
        for f in files:
            s, d = os.path.join(root, f), os.path.join(rel, f)
            if f == "missing.csv" and os.path.exists(d):
                with open(s, encoding="utf-8") as fs:
                    rows = fs.readlines()[1:]
                with open(d, "a", encoding="utf-8", newline="") as fd:
                    fd.writelines(rows)
            else:
                shutil.copyfile(s, d)
            n += 1
    return n


def main():
    src, label = sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "data"
    if not os.path.isdir(os.path.join(src, "data")):
        print("nothing to publish")
        return 0
    for attempt in range(1, 7):
        git("fetch", "--quiet", "origin", "main")
        git("reset", "--hard", "--quiet", "origin/main")
        n = merge_into_repo(src)
        git("add", "data")
        if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode == 0:
            print("no changes to commit")
            return 0
        git("commit", "--quiet", "-m", f"{label} ({n} files)")
        if git("push", "--quiet", "origin", "HEAD:main", check=False).returncode == 0:
            print(f"pushed on attempt {attempt}")
            return 0
        time.sleep(5 * attempt)
    print("push failed 6 times")
    return 1


if __name__ == "__main__":
    sys.exit(main())
