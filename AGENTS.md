# OALD10-Yomitan-Converter

Structure: single `main.py` parses OALD10 EN-ZH MDX text dump into Yomitan JSON (format 3 structured-content).

- `oaldpex/` — original MDX/MDD/CSS/JS source files (not processed)
- `yomitan_out/` — generated output (gitignored; created at runtime)
- `pyproject.toml` — uv project metadata (dependency: `beautifulsoup4`)

## Build workflow

```bash
# 1. Unpack the MDX (requires mdict-utils)
pip install mdict-utils
mdict -x oaldpe.mdx -d ./
# Rename output to oaldpe.txt next to main.py

# 2. Run the converter (uv auto-creates venv, installs bs4)
uv run python main.py
```

Output lands in `yomitan_out/`:

- `term_bank_N.json` (~10k entries each, format 3 structured-content)
- `styles.css` (ship alongside term banks in the zip)
- `dead_links_report.txt` (unresolvable redirects)

Manual steps after generation:

1. Create `index.json` with `"format": 3`, `"sourceLanguage": "en"`, `"targetLanguage": "zh"`
2. Create `tag_bank_1.json` (POS tags for Yomitan filtering)
3. Zip all `.json` files + `styles.css` together and import into Yomitan

## What the script does

1. Parses `oaldpe.txt` entry-by-entry (`</>` delimiter)
2. Resolves chained `@@@LINK=` redirects (Phase 2, report only — no redirect entries generated)
3. Generates `term_bank_N.json` files (Phase 3)

## Key changes from v1 (format 3 rewrite)

- **Format 3 structured-content** — definitions are JSON trees (`tag`/`content`/`data`), not raw strings
- **No phonetics** in term entries or HTML body
- **No AI-translated examples** — `[AI机翻]` tagged examples are skipped entirely
- **No inflection redirect entries** — `@@@LINK=` entries are resolved for dead-link checking but not output as term entries
- **No formatting commands** — no hooks, pre-commit, configs exist
- **Collapsible examples** — Yomitan natively toggles `example-sentence` extra-boxes

## Important

- The original MDX is **not** included (copyright); see README for Freemdict source
- `oaldpe.txt` must be in repo root (same dir as `main.py`)
- No tests, linting, or formatting config exist in this repo

## Output format

Term entry: `[word, "", pos, "", 0, [{type: "structured-content", content: tree}], seq_id, ""]`

CSS classes (used via `data-sc-*` attributes):

- `oald-entry`, `head`, `word`, `type`, `sense`, `num`, `idiom-label`, `meta`, `cf`, `eng-def`, `dfcn`, `extra-box`, `ex-en`, `ex-zh`, `xref`, `pv`, `pv-label`, `pv-link`

POS type colors are keyed off `data-sc-pos` attribute values (`verb`, `noun`, `adjective`, etc.).
