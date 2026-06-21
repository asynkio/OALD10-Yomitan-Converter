#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
OALD 10 to Yomitan Dictionary Converter (Format 3)
====================================================
Parses the OALD10 EN-ZH MDX text dump into Yomitan structured-content JSON
with CSS styling, collapsible examples, and no AI-translated content.

Features: CLI interface, auto-packaging (index/tag_bank/zip), multi-key
entries, multi-target redirects, strict DOM tag isolation, British/American
variants extraction, and dead-link forensics report.
"""

import json
import os
import re
import argparse
import shutil
import zipfile
import glob
from urllib.parse import quote
from bs4 import BeautifulSoup

VERSION = "2.1.0"


# ---------------------------------------------------------------------------
# Helper: extract meta tags from a container (labels/grammar/use/dis-g)
# ---------------------------------------------------------------------------


def _extract_meta_parts(container, tag_defs):
    """Extract ``[eng chn]`` meta strings from *container*.

    ``tag_defs`` is an iterable of ``(tag_name, [chn_subtag, ...])``
    tuples.  Chinese subtags are decomposed in-place so they don't
    pollute downstream text extraction.
    """
    parts = []
    for tag_name, chn_subtags in tag_defs:
        node = container.find("span", class_=tag_name)
        if not node:
            continue
        chn_text = ""
        if chn_subtags:
            cn = node.find(chn_subtags[0]) or node.find("chn")
            if cn:
                chn_text = cn.get_text(separator="", strip=True)
                for c in node.find_all(chn_subtags + ["chn"]):
                    c.decompose()
        eng = node.get_text(separator=" ", strip=True).strip("()[] ")
        txt = f"{eng} {chn_text}".strip()
        if txt:
            parts.append(f"[{txt}]")
    return parts


# ---------------------------------------------------------------------------
# Structured-content helpers (Yomitan format 3)
# ---------------------------------------------------------------------------


def node(tag, content=None, *, data=None, lang=None, style=None, href=None, title=None):
    """Build a structured-content tree node.

    ``data`` maps to ``data-sc-*`` HTML attributes (Yomitan prefixes
    every key with ``data-sc-``).  ``lang``, ``style``, ``href``,
    ``title`` become plain HTML attributes.
    """
    n = {"tag": tag}
    if content is not None:
        n["content"] = content
    attrs = {}
    if data:
        attrs.update(data)
    if lang is not None:
        n["lang"] = lang
    if style is not None:
        n["style"] = style
    if href is not None:
        n["href"] = href
    if title is not None:
        n["title"] = title
    if attrs:
        n["data"] = attrs
    return n


def build_entry(word, pos, senses, pv_links=None):
    """Assemble the structured-content tree for one word + POS."""
    parts = []

    # ---- Head ----
    head_parts = [node("span", word, data={"class": "word"})]
    if pos:
        pos_key = pos.lower().replace(" ", "-")
        head_parts.append(node("span", pos, data={"class": "type", "pos": pos_key}))
    parts.append(node("div", head_parts, data={"class": "head"}))

    # ---- Senses ----
    for i, sense in enumerate(senses):
        sp = []
        if len(senses) > 1:
            sp.append(node("span", chr(0x2460 + i) + " ", data={"class": "num"}))
        if sense.get("idiom"):
            sp.append(
                node("span", "⬩ " + sense["idiom"], data={"class": "idiom-label"})
            )
        if sense.get("meta"):
            sp.append(node("span", sense["meta"], data={"class": "meta"}))
        if sense.get("cf"):
            sp.append(node("span", sense["cf"], data={"class": "cf"}))
        if sense.get("variant_items"):
            # Group variants by label for compact display
            by_label = {}
            for vi in sense["variant_items"]:
                label = vi["label"]
                if label not in by_label:
                    by_label[label] = []
                by_label[label].append(vi["word"])
            for label, words in by_label.items():
                var_children = [f"[{label}: "]
                for j, w in enumerate(words):
                    if j > 0:
                        var_children.append(", ")
                    var_children.append(
                        node("a", w, href=f"?query={quote(w)}&wildcards=off")
                    )
                var_children.append("]")
                sp.append(node("span", var_children, data={"class": "variant"}))
        if sense.get("eng_def"):
            sp.append(node("span", sense["eng_def"], data={"class": "eng-def"}))
        if sense.get("chn_def"):
            sp.append(node("span", sense["chn_def"], data={"class": "dfcn"}, lang="zh"))

        # Collapsible examples
        for ex in sense.get("examples", []):
            inner = [
                node(
                    "div",
                    node("span", ex["en"], data={"class": "ex-en"}),
                    data={"content": "example-sentence-a"},
                )
            ]
            if ex.get("zh"):
                inner.append(
                    node(
                        "div",
                        node("span", ex["zh"], data={"class": "ex-zh"}, lang="zh"),
                        data={"content": "example-sentence-b"},
                    )
                )
            sp.append(
                node(
                    "div",
                    inner,
                    data={"class": "extra-box", "content": "example-sentence"},
                )
            )

        if sense.get("xref"):
            sp.append(sense["xref"])

        parts.append(node("div", sp, data={"class": "sense"}))

    # ---- Phrasal verbs ----
    if pv_links:
        pv_list = [
            node("span", "⬩ 相关短语动词 (Phrasal Verbs): ", data={"class": "pv-label"})
        ]
        for i, pv in enumerate(pv_links):
            if i > 0:
                pv_list.append(", ")
            pv_list.append(
                node(
                    "span",
                    node("a", pv, href=f"?query={quote(pv)}"),
                    data={"class": "pv-link"},
                )
            )
        parts.append(node("div", pv_list, data={"class": "pv"}))

    return node("div", parts, data={"class": "oald-entry"})


# ---------------------------------------------------------------------------
# Example extraction (skips AI machine translations)
# ---------------------------------------------------------------------------


def extract_examples(sense_li):
    """Return list of ``{"en": …, "zh": …}`` dicts from a sense ``<li>``.

    AI-translated examples are skipped entirely.  At most 5 examples
    are returned.
    """
    examples = []
    ex_ul = sense_li.find("ul", class_="examples")
    if not ex_ul:
        return examples
    for ex_li in ex_ul.find_all("li"):
        ex_span = ex_li.find("span", class_=["x", "unx"])
        if not ex_span:
            continue
        xt = ex_span.find(["xt", "unxt"])
        ex_chn = ""
        if xt:
            if xt.find("ai"):
                continue
            if xt.find("leon"):
                leon = xt.find("leon")
                ex_chn = "[个人审校] " + leon.get_text(separator="", strip=True)
                leon.decompose()
            elif xt.find("oald"):
                oald = xt.find("oald")
                ex_chn = "[旧版] " + oald.get_text(separator="", strip=True)
                oald.decompose()
            else:
                ex_chn = xt.get_text(separator="", strip=True)
            xt.decompose()
        if not ex_chn:
            continue

        # Construction-frame prefix for this example
        ex_cf_prefix = ""
        ex_cfs = ex_li.find_all("span", class_="cf")
        if ex_cfs:
            cf_texts = [c.get_text(separator=" ", strip=True) for c in ex_cfs]
            ex_cf_prefix = f"[{' | '.join(cf_texts)}] "
            for c in ex_cfs:
                c.decompose()

        ex_eng = ex_span.get_text(separator=" ", strip=True)
        ex_eng = re.sub(r"\s+", " ", ex_eng)
        ex_eng = re.sub(r"\s+([.,;?!:)])", r"\1", ex_eng)
        ex_eng = re.sub(r"(\()\s+", r"\1", ex_eng)
        ex_eng = f"{ex_cf_prefix}{ex_eng}".strip()
        if ex_eng:
            examples.append({"en": ex_eng, "zh": ex_chn})
    return examples[:5]


# ---------------------------------------------------------------------------
# Cross-reference extraction (creates query links)
# ---------------------------------------------------------------------------


def extract_xrefs(sense_li):
    """Extract cross-references as a structured-content ``div`` node.

    Each ``<span class="xrefs">`` becomes a ``div[data-sc-class="xref"]``
    with ``a[href="?query=WORD&wildcards=off"]`` links.
    Returns ``None`` when there are no cross-references.
    """
    xref_tags = sense_li.find_all("span", class_="xrefs")
    if not xref_tags:
        return None

    parts = []
    for idx, xtag in enumerate(xref_tags):
        prefix_tag = xtag.find("span", class_="prefix")
        prefix = prefix_tag.get_text(strip=True) if prefix_tag else ""

        links = []
        for a in xtag.find_all("a", class_="Ref"):
            xh = a.find("span", class_="xh")
            if not xh:
                continue
            display = xh.get_text(strip=True)
            if links:
                links.append(", ")
            links.append(
                node("a", display, href=f"?query={quote(display)}&wildcards=off")
            )

        if not links:
            continue

        if idx > 0:
            parts.append(node("br"))
        parts.append(node("span", f"◈ {prefix}: ", data={"class": "xref-label"}))
        parts.extend(links)

    if not parts:
        return None
    return node("div", parts, data={"class": "xref"})


# ---------------------------------------------------------------------------
# Metadata generation & auto-packaging
# ---------------------------------------------------------------------------


def generate_metadata_files(output_dir):
    """Generate Yomitan-required index.json and tag_bank_1.json."""
    index_data = {
        "title": "OALDe10-enzh",
        "format": 3,
        "revision": f"v{VERSION}",
        "sequenced": True,
        "author": "OALD10-Yomitan-Converter",
        "url": "https://github.com/asynkio/OALD10-Yomitan-Converter",
        "description": (
            "牛津高阶英汉双解词典（第 10 版）\n"
            "Oxford Advanced Learner's Dictionary (10th Edition) En-Zh.\n"
            "Includes phrasal verbs, idioms, and deduplicated multi-source definitions."
        ),
    }
    with open(os.path.join(output_dir, "index.json"), "w", encoding="utf-8") as f:
        json.dump(index_data, f, ensure_ascii=False, indent=2)
    print("  [+] Created index.json")

    tag_data = [
        ["noun", "partOfSpeech", 0, "名词 (Noun)", 0],
        ["verb", "partOfSpeech", 0, "动词 (Verb)", 0],
        ["adjective", "partOfSpeech", 0, "形容词 (Adjective)", 0],
        ["adverb", "partOfSpeech", 0, "副词 (Adverb)", 0],
        ["pronoun", "partOfSpeech", 0, "代词 (Pronoun)", 0],
        ["preposition", "partOfSpeech", 0, "介词 (Preposition)", 0],
        ["conjunction", "partOfSpeech", 0, "连词 (Conjunction)", 0],
        ["interjection", "partOfSpeech", 0, "感叹词 (Interjection)", 0],
        ["determiner", "partOfSpeech", 0, "限定词 (Determiner)", 0],
        ["idiom", "expression", 0, "习语 (Idiom)", 0],
        ["phrasal verb", "expression", 0, "动词短语 (Phrasal Verb)", 0],
        [
            "Oxford Advanced Learner's Dictionary",
            "dictionary",
            -10,
            "牛津高阶英汉双解词典 第10版",
            0,
        ],
    ]
    with open(os.path.join(output_dir, "tag_bank_1.json"), "w", encoding="utf-8") as f:
        json.dump(tag_data, f, ensure_ascii=False, separators=(",", ":"))
    print("  [+] Created tag_bank_1.json")


def package_and_cleanup(output_dir):
    """Zip all JSON files and styles.css into a ready-to-import archive,
    then delete temporary term_bank chunks."""
    zip_filename = f"OALD10_Yomitan_v{VERSION}.zip"
    zip_filepath = os.path.join(output_dir, zip_filename)

    index_file = os.path.join(output_dir, "index.json")
    tag_files = glob.glob(os.path.join(output_dir, "tag_bank_*.json"))
    term_banks = glob.glob(os.path.join(output_dir, "term_bank_*.json"))

    files_to_zip = []
    if os.path.exists(index_file):
        files_to_zip.append(index_file)
    files_to_zip.extend(tag_files)
    files_to_zip.extend(term_banks)

    # Ensure styles.css is copied into output dir and included in zip
    styles_src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "styles.css")
    styles_dst = os.path.join(output_dir, "styles.css")
    if os.path.exists(styles_src):
        shutil.copy2(styles_src, styles_dst)
        files_to_zip.append(styles_dst)

    if not files_to_zip:
        print("  [!] No files found to zip.  Skipping packaging.")
        return

    print(f"\n==> Packing dictionary into: {zip_filename}")

    with zipfile.ZipFile(zip_filepath, "w", zipfile.ZIP_DEFLATED) as zf:
        for fp in files_to_zip:
            arcname = os.path.basename(fp)
            print(f"    Adding {arcname}")
            zf.write(fp, arcname)

    print("==> Cleaning up temporary JSON chunks...")
    for fp in term_banks:
        try:
            os.remove(fp)
        except OSError as e:
            print(f"    [!] Failed to delete {os.path.basename(fp)}: {e}")

    print(f"==> Packaging complete!  Final file: {zip_filepath}")


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def parse_mdict_stable(input_file, output_dir):
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    print(f"=== OALD 10 to Yomitan Converter v{VERSION} ===")
    print(f"Input File:  {input_file}")
    print(f"Output Dir:  {output_dir}\n")

    # Common meta-tag definitions (tag_name, [chn_subtag, ...])
    META_GLOBAL = (
        ("labels", ["labelx", "chn"]),
        ("grammar", []),
        ("use", ["uset", "chn"]),
    )
    META_LOCAL = META_GLOBAL + (("dis-g", ["dtxtx", "chn"]),)

    # =======================================================
    # Phase 1: Parse Core Dictionary & Collect Redirects
    # =======================================================
    print("Phase 1/4: Building core vocabulary and extracting DOM structures...")
    real_entries = {}  # display_word -> [entry_dict, ...]
    redirects = {}  # mdx_key -> [target_key, ...]
    mdx_to_display = {}  # MDX key -> display form (for redirect resolution)

    if not os.path.exists(input_file):
        print(f"Error: '{input_file}' not found.  Unpack the MDX file first.")
        return

    with open(input_file, "r", encoding="utf-8") as f:
        buffer = []
        for line in f:
            line = line.strip()
            if line == "</>":
                entry_text = "\n".join(buffer)
                buffer = []
                lines = entry_text.split("\n")
                if len(lines) < 2:
                    continue

                words = [w.strip() for w in lines[0].split("|") if w.strip()]
                content = "".join(lines[1:])

                # ---- Redirect ----
                if "@@@LINK=" in content:
                    raw_target = content.replace("@@@LINK=", "").strip()
                    target = raw_target.split("|")[0].strip()
                    for w in words:
                        if w == target:
                            continue
                        if w not in redirects:
                            redirects[w] = []
                        if target not in redirects[w]:
                            redirects[w].append(target)
                    continue

                # ---- Standard entry ----
                soup = BeautifulSoup(content, "html.parser")

                # Extract display word from HTML headword; fall back to first MDX key.
                hw = soup.find("h1", class_="headword")
                display_word = hw.get_text(strip=True) if hw else words[0]
                display_word = re.sub(r"[\u2000-\u200A\u202F\u00A0]", " ", display_word)
                for w in words:
                    mdx_to_display[w] = display_word

                entries_list = []
                entry_blocks = soup.find_all("div", class_="entry")
                if not entry_blocks:
                    entry_blocks = soup.find_all("span", class_="idm-g")

                for entry_block in entry_blocks:
                    pos_tag = entry_block.find("span", class_="pos")
                    pos = pos_tag.get_text(strip=True) if pos_tag else ""
                    if (
                        not pos
                        and entry_block.name == "span"
                        and "idm-g" in entry_block.get("class", [])
                    ):
                        pos = "idiom"

                    # --- Global meta tags (entry level) ---
                    global_meta_parts = []
                    webtop = entry_block.find("div", class_="webtop")
                    if webtop:
                        global_meta_parts = _extract_meta_parts(webtop, META_GLOBAL)

                    raw_senses = entry_block.find_all("li", class_="sense")
                    sense_data = []

                    for sense in raw_senses:
                        # --- Local meta tags ---
                        # 1) tags inside <span class="sensetop">
                        local_meta_parts = []
                        sensetop = sense.find("span", class_="sensetop")
                        if sensetop:
                            local_meta_parts = _extract_meta_parts(sensetop, META_LOCAL)

                        # 2) tags that are direct children of <li class="sense">
                        #    but outside <span class="sensetop">
                        #    (e.g. chip: labels / grammar are siblings of sensetop)
                        for tag_name, chn_subtags in META_LOCAL:
                            for node in sense.find_all(
                                "span", class_=tag_name, recursive=False
                            ):
                                chn_text = ""
                                if chn_subtags:
                                    cn = node.find(chn_subtags[0]) or node.find("chn")
                                    if cn:
                                        chn_text = cn.get_text(separator="", strip=True)
                                        for c in node.find_all(chn_subtags + ["chn"]):
                                            c.decompose()
                                eng = node.get_text(separator=" ", strip=True).strip(
                                    "()[] "
                                )
                                txt = f"{eng} {chn_text}".strip()
                                if txt:
                                    local_meta_parts.append(f"[{txt}]")

                        # --- Idiom isolation: use idm_webtop meta, NOT global_meta ---
                        idiom_label = ""
                        idm_g = sense.find_parent("span", class_="idm-g")
                        if idm_g:
                            idm_tag = idm_g.find("span", class_="idm")
                            if idm_tag:
                                idiom_label = idm_tag.get_text(
                                    separator=" ", strip=True
                                )

                            idiom_meta_parts = []
                            idm_webtop = idm_g.find("div", class_="webtop")
                            if idm_webtop:
                                idiom_meta_parts = _extract_meta_parts(
                                    idm_webtop, META_GLOBAL
                                )
                            combined_meta = idiom_meta_parts + local_meta_parts
                        else:
                            combined_meta = global_meta_parts + local_meta_parts

                        meta_info = " ".join(
                            dict.fromkeys(combined_meta)
                        )  # dedup preserving order

                        # --- British / American variant cross-references ---
                        variant_items = []
                        variant_tags = sense.find_all(
                            ["div", "span"], class_="variants"
                        )
                        if variant_tags:
                            for var in variant_tags:
                                for vg in var.find_all("span", class_="v-g"):
                                    # Determine region label from <span class="labels">
                                    region_label = "对应词"
                                    labels_tag = vg.find("span", class_="labels")
                                    if labels_tag:
                                        raw_title = labels_tag.get("title", "")
                                        has_en = "英式" in raw_title
                                        has_am = "美式" in raw_title
                                        if has_en and not has_am:
                                            region_label = "英式对应词"
                                        elif has_am and not has_en:
                                            region_label = "美式对应词"

                                    # Extract the reference word(s)
                                    v_tag = vg.find("span", class_="v")
                                    if v_tag:
                                        word_text = v_tag.get_text(
                                            separator=" ", strip=True
                                        )
                                        if word_text:
                                            variant_items.append(
                                                {
                                                    "label": region_label,
                                                    "word": word_text,
                                                }
                                            )
                                var.decompose()

                        # --- English definition ---
                        def_tag = sense.find("span", class_="def")
                        eng_def = (
                            def_tag.get_text(separator=" ", strip=True)
                            if def_tag
                            else ""
                        )

                        # --- Construction frames (not inside example lists) ---
                        cf_tags = sense.find_all("span", class_="cf")
                        main_cfs = [
                            cf
                            for cf in cf_tags
                            if not cf.find_parent("ul", class_="examples")
                        ]
                        cf_text = ""
                        if main_cfs:
                            cf_text = " | ".join(
                                c.get_text(separator=" ", strip=True) for c in main_cfs
                            )

                        # --- Chinese definition ---
                        chn_def = ""
                        # Decompose label-like spans to prevent their <chn>
                        # subtags from being mistaken as the definition
                        for label_class in ("labels", "grammar", "use", "dis-g"):
                            for label_tag in sense.find_all("span", class_=label_class):
                                label_tag.decompose()
                        deft_tag = sense.find("deft") or sense.find("chn")
                        if deft_tag:
                            for ai in deft_tag.find_all("ai"):
                                t = ai.get_text(separator="", strip=True)
                                if t:
                                    ai.replace_with(f"[AI机翻] {t}")
                            for leon in deft_tag.find_all("leon"):
                                t = leon.get_text(separator="", strip=True)
                                if t:
                                    leon.replace_with(f"[个人审校] {t}")
                            chn_def = deft_tag.get_text(separator=" ", strip=True)

                        # --- Cross-references ---
                        xref_node = extract_xrefs(sense)

                        if not eng_def and not chn_def:
                            continue

                        # --- Examples ---
                        examples = extract_examples(sense)

                        sense_data.append(
                            {
                                "meta": meta_info or None,
                                "cf": cf_text or None,
                                "eng_def": eng_def or None,
                                "chn_def": chn_def or None,
                                "examples": examples,
                                "xref": xref_node,
                                "idiom": idiom_label or None,
                                "variant_items": variant_items or None,
                            }
                        )

                    # --- Phrasal-verb links ---
                    pv_aside = entry_block.find("aside", class_="phrasal_verb_links")
                    pv_links = []
                    if pv_aside:
                        pv_links = [
                            pv.get_text(separator=" ", strip=True)
                            for pv in pv_aside.find_all("span", class_="xh")
                        ]

                    if sense_data or pv_links:
                        tree = build_entry(
                            display_word, pos, sense_data, pv_links or None
                        )
                        entries_list.append({"pos": pos, "tree": tree})

                if entries_list:
                    real_entries[display_word] = entries_list
            else:
                buffer.append(line)

    print(
        f"  [ok] Phase 1 Complete.  "
        f"Core entries: {len(real_entries)}, "
        f"Redirects: {len(redirects)}"
    )

    # =======================================================
    # Phase 2: Resolve chained redirects (dead-link audit only)
    # =======================================================
    print("\nPhase 2/4: Resolving chained redirects...")
    dead_links_report = []

    for word, targets in redirects.items():
        if word in real_entries:
            continue
        for t in targets:
            current_target = t
            visited = {word}
            while current_target in redirects and current_target not in visited:
                visited.add(current_target)
                current_target = redirects[current_target][0]

            resolved_display = mdx_to_display.get(current_target, current_target)
            if resolved_display not in real_entries:
                dead_links_report.append(f"{word}  ==指向==>  {t}")

    print(f"  [ok] Phase 2 Complete.  Dead links: {len(dead_links_report)}")

    if dead_links_report:
        report_path = os.path.join(output_dir, "dead_links_report.txt")
        with open(report_path, "w", encoding="utf-8") as df:
            df.write(
                f"=== OALD 10 Dead Links Report ({len(dead_links_report)} total) ===\n\n"
            )
            df.write("\n".join(sorted(set(dead_links_report))))
        print(f"  [!] Dead links report: {report_path}")

    # =======================================================
    # Phase 3: Generate term banks
    # =======================================================
    print("\nPhase 3/4: Generating Yomitan data chunks...")

    # Clean up old term banks
    for fname in os.listdir(output_dir):
        if re.match(r"term_bank_\d+\.json$", fname):
            os.remove(os.path.join(output_dir, fname))

    def save_bank(data, index):
        path = os.path.join(output_dir, f"term_bank_{index}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=None)

    term_bank = []
    file_index = 1
    count = 0

    def flush_bank():
        nonlocal term_bank, file_index
        save_bank(term_bank, file_index)
        print(f"    term_bank_{file_index}.json  (Progress: {count})")
        term_bank = []
        file_index += 1

    for word, entries in real_entries.items():
        for entry_data in entries:
            term_entry = [
                word,
                "",
                entry_data["pos"],
                "",
                0,
                [{"type": "structured-content", "content": entry_data["tree"]}],
                count,
                "",
            ]
            term_bank.append(term_entry)
            count += 1
            if len(term_bank) >= 10000:
                flush_bank()

    if term_bank:
        flush_bank()

    print(f"  [ok] Phase 3 Complete.  Total valid entries: {count}")

    # =======================================================
    # Phase 4: Metadata generation & auto-packaging
    # =======================================================
    print("\nPhase 4/4: Generating metadata and packaging...")
    generate_metadata_files(output_dir)
    package_and_cleanup(output_dir)

    print(f"\nAll done!  Total entries: {count}")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Convert unpacked OALD10 MDX text to Yomitan JSON (format 3)."
    )
    parser.add_argument(
        "-i",
        "--input",
        required=True,
        help="Path to the unpacked oaldpe.txt file",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="./yomitan_out",
        help="Directory for generated Yomitan files (default: ./yomitan_out)",
    )
    args = parser.parse_args()
    parse_mdict_stable(args.input, args.output)
