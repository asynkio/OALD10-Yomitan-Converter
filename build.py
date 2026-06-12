#!/usr/bin/env python3
"""Build script for OALD10 Yomitan Dictionary.
Automates dependency install, MDX unpacking, parsing, and packaging.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
INPUT_MDX = PROJECT_DIR / "oaldpex/oaldpe.mdx"
INPUT_TXT = PROJECT_DIR / "oaldpe.txt"
OUTPUT_DIR = PROJECT_DIR / "yomitan_out"

INDEX_DATA = {
    "title": "OALDe10-enzh",
    "format": 3,
    "revision": "v1.1.0",
    "sequenced": True,
    "author": "Open Source Converter",
    "url": "https://github.com/asynkio/OALD10-Yomitan-Converter",
    "description": "牛津高阶英汉双解词典（第 10 版）\n\n内容由牛津大学出版社版权所有。本词典仅用于个人学习、研究用途。",
}


TAG_BANK = [
    ["n", "partOfSpeech", 0, "名词 (Noun)", 0],
    ["v", "partOfSpeech", 0, "动词 (Verb)", 0],
    ["adj", "partOfSpeech", 0, "形容词 (Adjective)", 0],
    ["adv", "partOfSpeech", 0, "副词 (Adverb)", 0],
    ["pron", "partOfSpeech", 0, "代词 (Pronoun)", 0],
    ["prep", "partOfSpeech", 0, "介词 (Preposition)", 0],
    ["conj", "partOfSpeech", 0, "连词 (Conjunction)", 0],
    ["intj", "partOfSpeech", 0, "感叹词 (Interjection)", 0],
    ["det", "partOfSpeech", 0, "限定词 (Determiner)", 0],
    ["idio", "expression", 0, "习语 (Idiom)", 0],
    ["phr-v", "expression", 0, "动词短语 (Phrasal Verb)", 0],
    [
        "Oxford Advanced Learner's Dictionary (10th China Edition)",
        "dictionary",
        -10,
        "牛津高阶英汉双解词典 第10版",
        0,
    ],
]


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
            f"Download it from Freemdict and place the oaldpex folder in {PROJECT_DIR}."
            f"Make sure that {PROJECT_DIR}/oaldpex/oaldpe.mdx exist."
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
    if has_uv():
        run(["uv", "run", "python", "main.py"], cwd=PROJECT_DIR)
    else:
        run([sys.executable, "main.py"], cwd=PROJECT_DIR)


def ensure_aux_files():
    step("Ensuring auxiliary files...")
    OUTPUT_DIR.mkdir(exist_ok=True)
    for name, data in [("index.json", INDEX_DATA), ("tag_bank_1.json", TAG_BANK)]:
        path = OUTPUT_DIR / name
        if not path.exists():
            print(f"    Creating {name}")
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        else:
            print(f"    {name} already exists — skipped")


def pack_zip():
    step("Packing Yomitan zip...")
    files = sorted(OUTPUT_DIR.glob("*.json"))
    css = OUTPUT_DIR / "styles.css"
    if css.exists():
        files.append(css)
    zip_path = PROJECT_DIR / "oald10_yomitan.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for fp in files:
            print(f"    Adding {fp.name}")
            zf.write(fp, arcname=fp.name)
    print(f"\n    Zip created: {zip_path}")


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
        help="Skip final zip packaging",
    )
    args = parser.parse_args()

    check_python()
    needs_unpack = check_inputs(args.skip_unpack)

    if needs_unpack:
        install_mdict_utils()
        unpack_mdx()

    install_project_deps()
    run_parser()
    ensure_aux_files()

    if not args.no_zip:
        pack_zip()

    print("\nBuild complete!")


if __name__ == "__main__":
    main()
