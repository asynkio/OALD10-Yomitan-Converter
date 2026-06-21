#!/usr/bin/env python3
"""Build script for OALD10 Yomitan Dictionary.
Automates dependency install, MDX unpacking, and parsing.
(Metadata generation, zip packaging, and cleanup are now handled by main.py.)
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
INPUT_MDX = PROJECT_DIR / "oaldpex" / "oaldpe.mdx"
INPUT_TXT = PROJECT_DIR / "oaldpe.txt"
OUTPUT_DIR = PROJECT_DIR / "yomitan_out"


def step(msg):
    print(f"\n==> {msg}")


def run(cmd, **kwargs):
    print(f"    $ {' '.join(str(c) for c in cmd)}")
    subprocess.run(cmd, check=True, **kwargs)


def has_uv():
    return shutil.which("uv") is not None


def check_python():
    if sys.version_info < (3, 10):
        print(
            f"Python 3.10+ required (found {sys.version_info.major}.{sys.version_info.minor})"
        )
        sys.exit(1)
    step(
        f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    )


def check_inputs(skip_unpack):
    if INPUT_TXT.exists():
        return False
    if not INPUT_MDX.exists():
        print(
            f"Error: {INPUT_MDX.name} not found.\n"
            f"Download it from Freemdict and place the oaldpex folder in {PROJECT_DIR}.\n"
            f"Make sure {INPUT_MDX} exists."
        )
        sys.exit(1)
    if skip_unpack:
        print(f"Error: --skip-unpack but {INPUT_TXT.name} not found")
        sys.exit(1)
    return True


def install_mdict_utils():
    step("Installing mdict-utils...")
    if has_uv():
        run(["uv", "pip", "install", "mdict-utils"])
    else:
        run([sys.executable, "-m", "pip", "install", "mdict-utils"])


def unpack_mdx():
    step("Unpacking MDX...")
    if has_uv():
        run(["uv", "run", "mdict", "-x", str(INPUT_MDX), "-d", "./"], cwd=PROJECT_DIR)
    else:
        run(["mdict", "-x", str(INPUT_MDX), "-d", "./"], cwd=PROJECT_DIR)


def install_project_deps():
    step("Installing project dependencies...")
    if has_uv():
        run(["uv", "sync"], cwd=PROJECT_DIR)
    else:
        run([sys.executable, "-m", "pip", "install", "-e", "."], cwd=PROJECT_DIR)


def run_parser():
    step("Parsing dictionary entries (this may take a while)...")
    args = [
        "-i",
        str(INPUT_TXT),
        "-o",
        str(OUTPUT_DIR),
    ]
    if has_uv():
        run(
            ["uv", "run", "python", "main.py"] + args,
            cwd=PROJECT_DIR,
        )
    else:
        run([sys.executable, "main.py"] + args, cwd=PROJECT_DIR)


def main():
    parser = argparse.ArgumentParser(
        description="Build the OALD10 Yomitan dictionary from MDX source"
    )
    parser.add_argument(
        "--skip-unpack",
        action="store_true",
        help="Skip MDX unpack (use existing oaldpe.txt)",
    )
    parser.add_argument(
        "--no-zip",
        action="store_true",
        help="[DEPRECATED] Packaging is now handled by main.py.  Use -o to control output.",
    )
    args = parser.parse_args()

    check_python()
    needs_unpack = check_inputs(args.skip_unpack)

    if needs_unpack:
        install_mdict_utils()
        unpack_mdx()

    install_project_deps()
    run_parser()

    print("\nBuild complete!")


if __name__ == "__main__":
    main()
