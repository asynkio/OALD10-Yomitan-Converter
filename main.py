"""
OALD 10 to Yomitan Dictionary Converter (Format 3)
====================================================
Parses the OALD10 EN-ZH MDX text dump into Yomitan structured-content JSON
with CSS styling, collapsible examples, and no AI-translated content.
"""

import json
import os
import re
from urllib.parse import quote
from bs4 import BeautifulSoup

INPUT_FILE = "oaldpe.txt"
OUTPUT_DIR = "yomitan_out"

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)


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

    # ---- Senses ----
    for i, sense in enumerate(senses):
        sp = []
        if len(senses) > 1:
            sp.append(node("span", chr(0x2460 + i) + " ", data={"class": "num"}))
        if sense.get("idiom"):
            sp.append(
                node("span", "◆ " + sense["idiom"], data={"class": "idiom-label"})
            )
        if sense.get("meta"):
            sp.append(node("span", sense["meta"], data={"class": "meta"}))
        if sense.get("cf"):
            sp.append(node("span", sense["cf"], data={"class": "cf"}))
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
            node("span", "◆ 相关短语动词 (Phrasal Verbs): ", data={"class": "pv-label"})
        ]
        for i, pv in enumerate(pv_links):
            if i > 0:
                pv_list.append(", ")
            pv_list.append(node("span", pv, data={"class": "pv-link"}))
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
# Main pipeline
# ---------------------------------------------------------------------------


def parse_mdict():
    print("Phase 1: Building Core Dictionary & Collecting Redirects...")
    real_entries = {}
    redirects = {}
    mdx_to_display = {}  # MDX key → display form (for redirect resolution)

    if not os.path.exists(INPUT_FILE):
        print(f"Error: {INPUT_FILE} not found.  Unpack the MDX file first.")
        return

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        buffer = []
        for line in f:
            line = line.strip()
            if line != "</>":
                buffer.append(line)
                continue

            entry_text = "\n".join(buffer)
            buffer = []
            lines = entry_text.split("\n")
            if len(lines) < 2:
                continue
            mdx_key = lines[0].strip()
            content = "".join(lines[1:])

            # Redirect
            if "@@@LINK=" in content:
                target = content.replace("@@@LINK=", "").strip()
                redirects[mdx_key] = target
                continue

            soup = BeautifulSoup(content, "html.parser")

            # Use the correct display form from HTML rather than the MDX key.
            # Normalise thin spaces (U+2009) etc. to regular spaces so that
            # user-typed queries match.
            hw = soup.find("h1", class_="headword")
            word = hw.get_text(strip=True) if hw else mdx_key
            word = re.sub(r"[\u2000-\u200A\u202F\u00A0]", " ", word)
            mdx_to_display[mdx_key] = word

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

                # --- Global meta tags ---
                global_meta = []
                webtop = entry_block.find("div", class_="webtop")
                if webtop:
                    for tag_name, chn_subtags in (
                        ("labels", ["labelx", "chn"]),
                        ("grammar", []),
                        ("use", ["uset", "chn"]),
                    ):
                        g_node = webtop.find("span", class_=tag_name)
                        if not g_node:
                            continue
                        chn_text = ""
                        if chn_subtags:
                            cn = g_node.find(chn_subtags[0]) or g_node.find("chn")
                            if cn:
                                chn_text = cn.get_text(separator="", strip=True)
                                for c in g_node.find_all(chn_subtags + ["chn"]):
                                    c.decompose()
                        eng = g_node.get_text(separator=" ", strip=True).strip("()[] ")
                        txt = f"{eng} {chn_text}".strip()
                        if txt:
                            global_meta.append(f"【{txt}】")

                raw_senses = entry_block.find_all("li", class_="sense")
                sense_data = []

                for sense in raw_senses:
                    # Local meta tags
                    local_meta = []
                    for tag_name, chn_subtags in (
                        ("labels", ["labelx", "chn"]),
                        ("grammar", []),
                        ("use", ["uset", "chn"]),
                        ("dis-g", ["dtxtx", "chn"]),
                    ):
                        l_node = sense.find("span", class_=tag_name)
                        if not l_node:
                            continue
                        chn_text = ""
                        if chn_subtags:
                            cn = l_node.find(chn_subtags[0]) or l_node.find("chn")
                            if cn:
                                chn_text = cn.get_text(separator="", strip=True)
                                for c in l_node.find_all(chn_subtags + ["chn"]):
                                    c.decompose()
                        eng = l_node.get_text(separator=" ", strip=True).strip("()[] ")
                        txt = f"{eng} {chn_text}".strip()
                        if txt:
                            local_meta.append(f"【{txt}】")

                    combined_meta = global_meta + local_meta
                    meta_info = "".join(dict.fromkeys(combined_meta))

                    # English definition
                    def_tag = sense.find("span", class_="def")
                    eng_def = (
                        def_tag.get_text(separator=" ", strip=True) if def_tag else ""
                    )

                    # Construction frames (not inside example lists)
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

                    # Chinese definition
                    chn_def = ""
                    deft_tag = sense.find(["deft", "chn"])
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

                    # Cross-references (clickable query links)
                    xref_node = extract_xrefs(sense)

                    if not eng_def and not chn_def:
                        continue

                    # Idiom label from enclosing <span class="idm-g">
                    idiom_label = ""
                    idm_g = sense.find_parent("span", class_="idm-g")
                    if idm_g:
                        idm_tag = idm_g.find("span", class_="idm")
                        if idm_tag:
                            idiom_label = idm_tag.get_text(separator=" ", strip=True)

                    # Examples
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
                        }
                    )

                # Phrasal-verb links (rescue stubs as well)
                pv_aside = entry_block.find("aside", class_="phrasal_verb_links")
                pv_links = []
                if pv_aside:
                    pv_links = [
                        pv.get_text(separator=" ", strip=True)
                        for pv in pv_aside.find_all("span", class_="xh")
                    ]

                if sense_data or pv_links:
                    tree = build_entry(word, pos, sense_data, pv_links or None)
                    entries_list.append({"pos": pos, "tree": tree})

            if entries_list:
                real_entries[word] = entries_list

    print(
        f"Phase 1 Complete.  "
        f"Core entries: {len(real_entries)}, "
        f"Raw redirects: {len(redirects)}"
    )

    # ---- Phase 2: Resolve chained redirects (kept for dead-link report) ----
    print("Phase 2: Resolving Chained Redirects...")
    dead_links = []
    for word, target in redirects.items():
        visited = {word}
        while target in redirects and target not in visited:
            visited.add(target)
            target = redirects[target]
        # Redirect target is an MDX key; look up its display form.
        resolved = mdx_to_display.get(target, target)
        if resolved not in real_entries:
            dead_links.append(f"{word}  ==指向==>  {target}")

    if dead_links:
        report = os.path.join(OUTPUT_DIR, "dead_links_report.txt")
        with open(report, "w", encoding="utf-8") as f:
            f.write(f"=== OALD 10 Dead Links Report ({len(dead_links)} total) ===\n\n")
            f.write("\n".join(dead_links))
        print(f"Dead links report: {report} ({len(dead_links)} entries)")

    # ---- Phase 3: Generate term banks (format 3 structured content) ----
    print("Phase 3: Generating Yomitan JSON Banks...")

    # Remove old term banks but preserve other files
    for fname in os.listdir(OUTPUT_DIR):
        if re.match(r"term_bank_\d+\.json$", fname):
            os.remove(os.path.join(OUTPUT_DIR, fname))

    term_bank = []
    file_index = 1
    count = 0

    def save_bank(data, idx):
        path = os.path.join(OUTPUT_DIR, f"term_bank_{idx}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=None)

    for word, entries in real_entries.items():
        for entry in entries:
            term_entry = [
                word,
                "",
                entry["pos"],
                "",
                0,
                [{"type": "structured-content", "content": entry["tree"]}],
                count,
                "",
            ]
            term_bank.append(term_entry)
            count += 1
            if len(term_bank) >= 10000:
                save_bank(term_bank, file_index)
                print(f"Generated term_bank_{file_index}.json  (Progress: {count})")
                term_bank = []
                file_index += 1

    if term_bank:
        save_bank(term_bank, file_index)
        print(f"Generated term_bank_{file_index}.json  (Final batch)")

    print(f"\nAll done!  Total valid entries: {count}")


if __name__ == "__main__":
    parse_mdict()
