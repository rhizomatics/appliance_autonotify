"""Compress the PNGs given in place with pngquant, as a pre-commit hook, so the docs build needn't optimise images

Run by prek on the PNGs being committed, with pngquant from the `pngquant-cli` wheel, so nothing needs installing
beyond the hook's own environment. A PNG pngquant can't make smaller, such as one already compressed, is left as it
is, so committing it again changes nothing.
"""

import shutil
import subprocess
import sys

# Material's own optimize plugin settings, so the images are as they were when the docs build compressed them
ARGS = ["--force", "--ext", ".png", "--strip", "--skip-if-larger", "--speed", "3"]
# pngquant's exit codes for a file it left alone: not smaller, or not within a quality range
LEFT_ALONE = {98, 99}


def main(paths: list[str]) -> int:
    pngquant = shutil.which("pngquant")
    if pngquant is None:
        print("pngquant isn't installed, see pngquant-cli", file=sys.stderr)
        return 1
    failed = 0
    for path in paths:
        result = subprocess.run([pngquant, *ARGS, path], check=False)
        if result.returncode not in (0, *LEFT_ALONE):
            print(f"pngquant failed on {path}: {result.returncode}", file=sys.stderr)
            failed = 1
    return failed


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
