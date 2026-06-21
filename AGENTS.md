# OALD10-Yomitan-Converter

Structure: `main.py` parses OALD10 EN-ZH MDX text dump into Yomitan JSON (format 3 structured-content). `build.py` orchestrates MDX unpacking and runs `main.py`.

- `oaldpex/` — original MDX/MDD/CSS/JS source files (not processed)
- `yomitan_out/` — generated output (gitignored; created at runtime). Contains:
  - `term_bank_N.json` — generated chunk files (~10k entries each; cleaned up after zip packaging)
  - `index.json` — auto-generated Yomitan dictionary metadata
  - `tag_bank_1.json` — auto-generated POS colour tags for native Yomitan highlighting
  - `dead_links_report.txt` — unresolvable redirect chains
  - `OALD10_Yomitan_v*.zip` — ready-to-import Yomitan archive (auto-generated)
- `styles.css` — core dictionary styles (auto-copied into output dir and baked into zip by `main.py`)
- `custom.css` — optional study-aid CSS (blur/hide Chinese, for Yomitan custom CSS)
- `build.py` — orchestrator: unpack MDX → install deps → run `main.py`
- `pyproject.toml` — uv project metadata (dependency: `beautifulsoup4`)

## Build workflow

```bash
# 1. Unpack the MDX (requires mdict-utils)
pip install mdict-utils
mdict -x oaldpe.mdx -d ./
# Rename output to oaldpe.txt next to main.py

# 2. Run the converter (handles everything: parse → metadata → zip → cleanup)
uv run python main.py -i oaldpe.txt -o yomitan_out

# Or use build.py for the full pipeline (unpack + parse):
uv run python build.py
# With existing oaldpe.txt:
uv run python build.py --skip-unpack
```

Output lands in `yomitan_out/`. After generation, the final zip is ready to import into Yomitan.
Manual steps: paste `custom.css` into Yomitan's Custom CSS for study-aid interactions.

## What the script does

1. **Phase 1** — Parses `oaldpe.txt` entry-by-entry (`</>` delimiter). Handles `|`-separated multi-key entries. Extracts structured-content trees (format 3) with CSS-styled heads, senses, collapsible examples, cross-references, phrasal verb links, and variant references with regional labels.
2. **Phase 2** — Resolves chained `@@@LINK=` redirects for dead-link auditing only. Logs unresolvable chains to `dead_links_report.txt`. Redirect-derived entries are **not** generated — Yomitan's built-in deinflector handles inflectional forms natively.
3. **Phase 3** — Generates `term_bank_N.json` files from core entries (score 0).
4. **Phase 4** — Auto-generates `index.json` and `tag_bank_1.json`, copies `styles.css` into output dir, zips all files into `OALD10_Yomitan_v*.zip`, then cleans up temporary term_bank chunks.

## CLI usage

```
uv run python main.py -i oaldpe.txt -o yomitan_out
uv run python main.py --input /path/to/oaldpe.txt --output /path/to/out
```

## Key features (v2.1)

- **CLI interface** — `-i`/`-o` arguments; no hardcoded paths
- **Auto-packaging** — `index.json`, `tag_bank_1.json`, and ZIP archive generated automatically
- **Strict DOM tag isolation** — local meta scoped to `sensetop` + sense direct children; idiom meta uses `idm_webtop` (no pollution from parent entry's global meta)
- **Multi-key entries** — `|`-separated MDX keys correctly associated with all spellings
- **British/American variants** — extracted from `variants` tags as independent structured elements with regional labels (`英式对应词` / `美式对应词`) and clickable query links
- **Data forensics** — `dead_links_report.txt` provides transparent audit trail of unresolvable redirects
- **No phonetics** in term entries or HTML body
- **No AI-translated examples** — `[AI机翻]` tagged examples are skipped entirely
- **No redirect-derived entries** — `@@@LINK=` entries are resolved for reporting only; Yomitan handles inflection via its native deinflector
- **Collapsible examples** — Yomitan natively toggles `example-sentence` extra-boxes

## Important

- The original MDX is **not** included (copyright); see README for Freemdict source
- `oaldpe.txt` must be in repo root (same dir as `main.py`)
- No tests, linting, or formatting config exist in this repo

## Output format

Term entry: `[word, "", pos, "", 0, [{type: "structured-content", content: tree}], seq_id, ""]`

All entries use score `0` (core entries only — no redirect-derived entries).

CSS classes (used via `data-sc-*` attributes):

- `oald-entry`, `head`, `word`, `type`, `sense`, `num`, `idiom-label`, `meta`, `cf`, `variant`, `var-label`, `eng-def`, `dfcn`, `extra-box`, `ex-en`, `ex-zh`, `xref`, `xref-label`, `pv`, `pv-label`, `pv-link`

POS type colours are keyed off `data-sc-pos` attribute values (`verb`, `noun`, `adjective`, etc.).
