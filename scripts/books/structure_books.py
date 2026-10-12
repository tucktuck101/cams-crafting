#!/usr/bin/env python3
"""Convert official D&D book Markdown (ref/books/*.md) into 5etools-format
book/bookData JSON (ref/5etools/books/<SOURCE>.json), plus a flat section
index (ref/5etools/sections.jsonl) and the source mapping table
(ref/5etools/sources.json).

Python 3 stdlib only. Run: python3 scripts/books/structure_books.py

Wave 1: structure only (headings -> section/entries, paragraphs, lists,
tables, insets/quotes, bold-italic lead-ins, inline {@b}/{@i} formatting).
No entity extraction - sections.jsonl only *guesses* categories/entities
for later waves to pick up.
"""
from __future__ import annotations

import html
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BOOKS_DIR = REPO_ROOT / "ref" / "books"
OUT_DIR = REPO_ROOT / "ref" / "5etools"
OUT_BOOKS_DIR = OUT_DIR / "books"
SOURCES_JSON = OUT_DIR / "sources.json"
SECTIONS_JSONL = OUT_DIR / "sections.jsonl"

GEN_TIME = int(time.time())

# ---------------------------------------------------------------------------
# 1. Source mapping table
#
# Every (file, source code, id, full title, group, published date, authors)
# below was cross-checked against the official 5etools site data
# (data/books.json in the 5etools-src repo, fetched 2026-10-12) by matching
# book id. All 51 matched an existing official entry - none needed an
# invented code. `kind` is "book"/bookData for all 51: none of these titles
# appear in the official adventures.json index (that list only contains
# true adventure modules such as Curse of Strahd, none of which are present
# in ref/books/).
# ---------------------------------------------------------------------------

# (filename, source, id, full title, group, published, authors)
_RAW_SOURCES = [
    ("Acquisitions Incorporated.md", "AI", "AI", "Acquisitions Incorporated", "supplement", "2019-06-18", ["Wizards RPG Team"]),
    ("Adventure Atlas_ The Mortuary.md", "AATM", "AATM", "Adventure Atlas: The Mortuary", "supplement-alt", "2023-10-17", ["Wizards RPG Team"]),
    ("Adventure with Muk.md", "AWM", "AWM", "Adventure with Muk", "supplement-alt", "2019-11-12", ["Emi Tanji"]),
    ("Adventurers League.md", "AL", "AL", "Adventurers League", "organized-play", "2016-08-26", ["Wizards RPG Team"]),
    ("Astral Adventurer's Guide.md", "AAG", "AAG", "Astral Adventurer's Guide", "setting", "2022-08-16", ["Wizards RPG Team"]),
    ("Bigby Presents_ Glory of the Giants.md", "BGG", "BGG", "Bigby Presents: Glory of the Giants", "supplement", "2023-08-15", ["Wizards RPG Team"]),
    ("Boo's Astral Menagerie.md", "BAM", "BAM", "Boo's Astral Menagerie", "setting", "2022-08-16", ["Wizards RPG Team"]),
    ("Domains of Delight.md", "DoD", "DoD", "Domains of Delight", "supplement-alt", "2021-09-21", ["Wizards RPG Team"]),
    ("Dungeon Master's Guide.md", "DMG", "DMG", "Dungeon Master's Guide (2014)", "core", "2014-12-09", ["Wizards RPG Team"]),
    ("Dungeon Master's Screen.md", "Screen", "Screen", "Dungeon Master's Screen", "screen", "2015-01-20", ["Wizards RPG Team"]),
    ("Dungeon Master's Screen_ Dungeon Kit.md", "ScreenDungeonKit", "ScreenDungeonKit", "Dungeon Master's Screen: Dungeon Kit", "screen", "2020-09-21", ["Wizards RPG Team"]),
    ("Dungeon Master's Screen_ Spelljammer.md", "ScreenSpelljammer", "ScreenSpelljammer", "Dungeon Master's Screen: Spelljammer", "screen", "2022-08-16", ["Wizards RPG Team"]),
    ("Dungeon Master's Screen_ Wilderness Kit.md", "ScreenWildernessKit", "ScreenWildernessKit", "Dungeon Master's Screen: Wilderness Kit", "screen", "2020-11-17", ["Wizards RPG Team"]),
    ("Dungeons & Dragons vs. Rick and Morty_ Basic Rules.md", "RMR", "RMR", "Dungeons & Dragons vs. Rick and Morty: Basic Rules", "supplement-alt", "2019-11-19", ["Wizards RPG Team"]),
    ("Eberron_ Rising from the Last War.md", "ERLW", "ERLW", "Eberron: Rising from the Last War", "setting", "2019-11-19", ["Wizards RPG Team"]),
    ("Explorer's Guide to Wildemount.md", "EGW", "EGW", "Explorer's Guide to Wildemount", "setting", "2020-03-17", ["Wizards RPG Team"]),
    ("Fizban's Treasury of Dragons.md", "FTD", "FTD", "Fizban's Treasury of Dragons", "supplement", "2021-10-26", ["Wizards RPG Team"]),
    ("Guildmasters' Guide to Ravnica.md", "GGR", "GGR", "Guildmasters' Guide to Ravnica", "setting", "2018-11-20", ["Wizards RPG Team"]),
    ("Heroes' Feast Flavors of the Multiverse.md", "HFFotM", "HFFotM", "Heroes' Feast Flavors of the Multiverse", "recipe", "2023-11-07", ["Wizards RPG Team"]),
    ("Heroes' Feast Legends of the Table.md", "HFLotT", "HFLotT", "Heroes' Feast Legends of the Table", "recipe", "2026-09-15", ["Wizards RPG Team"]),
    ("Heroes' Feast.md", "HF", "HF", "Heroes' Feast", "recipe", "2020-10-27", ["Wizards RPG Team"]),
    ("Minsc and Boo's Journal of Villainy.md", "MaBJoV", "MaBJoV", "Minsc and Boo's Journal of Villainy", "supplement-alt", "2021-10-05", ["Wizards RPG Team"]),
    ("Monster Manual.md", "MM", "MM", "Monster Manual (2014)", "core", "2014-09-30", ["Wizards RPG Team"]),
    ("Monstrous Compendium Volume 1_ Spelljammer Creatures.md", "MCV1SC", "MCV1SC", "Monstrous Compendium Volume 1: Spelljammer Creatures", "supplement-alt", "2022-04-21", ["Wizards RPG Team"]),
    ("Monstrous Compendium Volume 4_ Eldraine Creatures.md", "MCV4EC", "MCV4EC", "Monstrous Compendium Volume 4: Eldraine Creatures", "supplement-alt", "2023-09-21", ["Wizards RPG Team"]),
    ("Mordenkainen Presents_ Monsters of the Multiverse.md", "MPMM", "MPMM", "Mordenkainen Presents: Monsters of the Multiverse", "supplement", "2022-01-25", ["Wizards RPG Team"]),
    ("Mordenkainen's Tome of Foes.md", "MTF", "MTF", "Mordenkainen's Tome of Foes", "supplement", "2018-05-29", ["Wizards RPG Team"]),
    ("Morte's Planar Parade.md", "MPP", "MPP", "Morte's Planar Parade", "setting", "2023-10-07", ["Wizards RPG Team"]),
    ("Muk's Guide to Everything He Learned From Tasha.md", "MGELFT", "MGELFT", "Muk's Guide to Everything He Learned From Tasha", "supplement-alt", "2020-12-01", ["Wizards RPG Team"]),
    ("Mythic Odysseys of Theros.md", "MOT", "MOT", "Mythic Odysseys of Theros", "setting", "2020-06-02", ["Wizards RPG Team"]),
    ("One Grung Above.md", "OGA", "OGA", "One Grung Above", "supplement-alt", "2017-10-11", ["Wizards RPG Team"]),
    ("Plane Shift_ Amonkhet.md", "PSA", "PS-A", "Plane Shift: Amonkhet", "setting-alt", "2017-07-06", ["Wizards RPG Team"]),
    ("Plane Shift_ Dominaria.md", "PSD", "PS-D", "Plane Shift: Dominaria", "setting-alt", "2018-07-31", ["Wizards RPG Team"]),
    ("Plane Shift_ Innistrad.md", "PSI", "PS-I", "Plane Shift: Innistrad", "setting-alt", "2016-07-12", ["Wizards RPG Team"]),
    ("Plane Shift_ Ixalan.md", "PSX", "PS-X", "Plane Shift: Ixalan", "setting-alt", "2018-01-09", ["Wizards RPG Team"]),
    ("Plane Shift_ Kaladesh.md", "PSK", "PS-K", "Plane Shift: Kaladesh", "setting-alt", "2017-02-16", ["Wizards RPG Team"]),
    ("Plane Shift_ Zendikar.md", "PSZ", "PS-Z", "Plane Shift: Zendikar", "setting-alt", "2016-04-27", ["Wizards RPG Team"]),
    ("Player's Handbook.md", "PHB", "PHB", "Player's Handbook (2014)", "core", "2014-08-19", ["Wizards RPG Team"]),
    ("Puncheons and Flagons.md", "PaF", "PaF", "Puncheons and Flagons", "recipe", "2024-08-27", ["Wizards RPG Team"]),
    ("Sage Advice Compendium.md", "SAC", "SAC", "Sage Advice Compendium (2014)", "other", "2019-01-31", ["Wizards RPG Team"]),
    ("Sigil and the Outlands.md", "SatO", "SatO", "Sigil and the Outlands", "setting", "2023-10-07", ["Wizards RPG Team"]),
    ("Strixhaven_ A Curriculum of Chaos.md", "SCC", "SCC", "Strixhaven: A Curriculum of Chaos", "setting", "2021-12-07", ["Wizards RPG Team"]),
    ("Sword Coast Adventurer's Guide.md", "SCAG", "SCAG", "Sword Coast Adventurer's Guide", "setting", "2015-11-03", ["Wizards RPG Team"]),
    ("Tarot Deck.md", "TD", "TD", "Tarot Deck", "supplement-alt", "2022-05-24", ["Wizards RPG Team"]),
    ("Tasha's Cauldron of Everything.md", "TCE", "TCE", "Tasha's Cauldron of Everything", "supplement", "2020-11-17", ["Wizards RPG Team"]),
    ("The Book of Many Things.md", "BMT", "BMT", "The Book of Many Things", "supplement", "2023-11-14", ["Wizards RPG Team"]),
    ("The Deck of Many Things_ Card Reference Guide.md", "DMTCRG", "DMTCRG", "The Deck of Many Things: Card Reference Guide", "supplement", "2023-11-14", ["Wizards RPG Team"]),
    ("Thieves' Gallery.md", "HAT-TG", "HAT-TG", "Thieves' Gallery", "supplement-alt", "2023-03-06", ["Wizards RPG Team"]),
    ("Van Richten's Guide to Ravenloft.md", "VRGR", "VRGR", "Van Richten's Guide to Ravenloft", "setting", "2021-05-18", ["Wizards RPG Team"]),
    ("Volo's Guide to Monsters.md", "VGM", "VGM", "Volo's Guide to Monsters", "supplement", "2016-11-15", ["Wizards RPG Team"]),
    ("Xanathar's Guide to Everything.md", "XGE", "XGE", "Xanathar's Guide to Everything", "supplement", "2017-11-21", ["Wizards RPG Team"]),
]

SOURCES = [
    {
        "file": f,
        "source": src,
        "id": bid,
        "full": full,
        "kind": "book",
        "group": group,
        "published": pub,
        "authors": authors,
        "confidence": "official",
        "notes": "",
    }
    for (f, src, bid, full, group, pub, authors) in _RAW_SOURCES
]

# No ambiguous cases: every file matched an existing official 5etools source
# by exact/near-exact title match, and all 51 are classified "book" (none
# appear in the official adventures.json registry).
UNCERTAIN_BOOKS: list[str] = []

assert len({s["file"] for s in SOURCES}) == 51, "expected exactly 51 source rows"

# ---------------------------------------------------------------------------
# 2. HTML embed-div cleanup
#
# ~40/51 files were scraped from the live 5etools site and contain raw
# "loading..." placeholder <div> widgets wherever the original page had an
# inline {@tag} reference or a transcluded statblock (the real 5etools
# tag/statblock text was never captured, only hover-widget HTML). Each
# widget carries data-rd-tag/data-rd-name/data-rd-source/data-rd-uid
# attributes identifying exactly what was referenced, so we reconstruct a
# clean inline tag (or a `type:"statblock"` transclusion node when the
# widget was the *entire* content of a heading) instead of leaving raw HTML
# soup in the text.
# ---------------------------------------------------------------------------

_DIV_TAG_RE = re.compile(r"<(div)\b[^>]*>|</(div)>", re.IGNORECASE)
_TD_ATTR_RE = re.compile(r'<td colspan="6"([^>]*)>')
_ATTR_RE = re.compile(r'([a-zA-Z0-9_-]+)="([^"]*)"')

# tagNameStats enum from the 5etools-utils brew schema (util.json) intersected
# with the data-rd-tag values actually observed in ref/books/*.md. Entries in
# this set are eligible for `type:"statblock"` reconstruction.
_STATBLOCK_TAGS = {
    "action", "background", "charoption", "class", "condition", "creature",
    "deck", "disease", "feat", "hazard", "item", "language", "object",
    "optfeature", "race", "recipe", "reward", "spell", "table", "trap",
    "variantrule", "vehicle",
}
# "deity" gets its own statblock branch (tag + name [+ pantheon]).
# "subclass" has no statblock branch that we can satisfy from the embed's
# attributes alone (it additionally requires shortName/className/classSource)
# so it always falls back to a plain inline {@subclass ...} tag.


def _embed_block_to_tag(block: str) -> str:
    """Given one balanced <div>...</div> embed-widget blob, return the
    equivalent `{@tag uid}` inline text, or "" if nothing identifiable was
    found (dropped silently)."""
    m = _TD_ATTR_RE.search(block)
    if not m:
        return ""
    attrs = dict(_ATTR_RE.findall(m.group(1)))
    tag = attrs.get("data-rd-tag") or ""
    page = attrs.get("data-rd-page") or ""
    uid = attrs.get("data-rd-uid") or ""
    if not tag:
        if page == "monsterFluff":
            tag = "creature"
        elif page == "recipeFluff":
            tag = "recipe"
    if not tag or not uid:
        return ""
    return "{@%s %s}" % (tag, uid)


def strip_embed_divs(text: str) -> str:
    """Replace every top-level balanced <div>...</div> embed widget with its
    reconstructed inline tag. Widgets that occupy whole line(s) by themselves
    (or are glued only to sibling embed widgets) are isolated onto their own
    paragraph so later whole-paragraph detection can promote them to a
    `type:"statblock"` node; widgets glued to real surrounding prose/markup
    are substituted in place so they merge into that paragraph."""
    blocks = []
    pos = 0
    while True:
        m = _DIV_TAG_RE.search(text, pos)
        if not m:
            break
        if not m.group(1):
            pos = m.end()
            continue
        start = m.start()
        depth = 1
        scan_pos = m.end()
        while depth > 0:
            m2 = _DIV_TAG_RE.search(text, scan_pos)
            if not m2:
                scan_pos = len(text)
                break
            depth += 1 if m2.group(1) else -1
            scan_pos = m2.end()
        blocks.append((start, scan_pos))
        pos = scan_pos

    if not blocks:
        return text

    pieces = []
    cursor = 0
    for (s, e) in blocks:
        pieces.append(text[cursor:s])
        tag_text = _embed_block_to_tag(text[s:e])
        if tag_text:
            is_start = s == 0 or text[s - 1] == "\n" or text[:s].endswith("</div>")
            is_end = e == len(text) or text[e] == "\n" or text[e:].startswith("<div")
            if is_start and is_end:
                pieces.append("\n\n" + tag_text + "\n\n")
            else:
                pieces.append(tag_text)
        cursor = e
    pieces.append(text[cursor:])
    return "".join(pieces)


_EMBED_TAG_FULL_RE = re.compile(r"^\{@([a-zA-Z]+)\s+([^{}]+)\}$")


def _uid_parts(uid: str) -> list[str]:
    return uid.split("|")


def finalize_embed_paragraph(tag: str, uid: str):
    """Build the final JSON node for a paragraph whose *entire* content is
    one reconstructed embed tag: a `type:"statblock"` transclusion when the
    schema supports it for this tag, else the bare inline tag string."""
    parts = _uid_parts(uid)
    name = parts[0] if parts else uid
    source = parts[-1] if len(parts) > 1 else ""
    if tag == "deity" and len(parts) == 3:
        out = {"type": "statblock", "tag": "deity", "name": name}
        if parts[1]:
            out["pantheon"] = parts[1]
        if source:
            out["source"] = source
        return out
    if tag in _STATBLOCK_TAGS and name and source:
        return {"type": "statblock", "tag": tag, "name": name, "source": source}
    return "{@%s %s}" % (tag, uid)


# ---------------------------------------------------------------------------
# 3. Inline formatting (markdown emphasis -> 5etools {@b}/{@i} tags)
# ---------------------------------------------------------------------------

_IMG_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_BOLD_ITALIC_RE = re.compile(r"\*\*\*([^*]+?)\*\*\*")
_BOLD_RE = re.compile(r"\*\*([^*]+?)\*\*")
_UBOLD_RE = re.compile(r"__([^_]+?)__")
_STRIKE_RE = re.compile(r"~~([^~]+?)~~")
_ITALIC_RE = re.compile(r"(?<!\*)\*([^*\n]+?)\*(?!\*)")
_WS_RE = re.compile(r"[ \t]+")


def convert_inline(text: str) -> str:
    if not text:
        return text
    if _EMBED_TAG_FULL_RE.match(text.strip()):
        return text.strip()
    text = _IMG_RE.sub("", text)
    text = _BOLD_ITALIC_RE.sub(lambda m: "{@b {@i %s}}" % m.group(1), text)
    text = _BOLD_RE.sub(lambda m: "{@b %s}" % m.group(1), text)
    text = _UBOLD_RE.sub(lambda m: "{@b %s}" % m.group(1), text)
    text = _STRIKE_RE.sub(lambda m: "{@s %s}" % m.group(1), text)
    text = _ITALIC_RE.sub(lambda m: "{@i %s}" % m.group(1), text)
    text = _WS_RE.sub(" ", text)
    return text.strip()


_LEADIN_RE = re.compile(r"^\*\*\*([^*]+?)\*\*\*\s*(.*)$", re.DOTALL)


def split_bold_italic_leadin(paragraph_text: str):
    m = _LEADIN_RE.match(paragraph_text.strip())
    if not m:
        return None
    name = m.group(1).strip()
    if name.endswith("."):
        name = name[:-1]
    rest = m.group(2).strip()
    return name, rest


# ---------------------------------------------------------------------------
# 4. Heading-line repair
#
# A handful of lines in the source lost the newline between a heading and
# the bullet list that should follow it (e.g.
# "##### Questions to ask:- How do you..."). Split those back into a clean
# heading line + a synthetic bullet line wherever a hyphen is glued directly
# to the previous word and immediately followed by a bullet-like continuation
# (space+capital, or a bold run) - true hyphenated compound words in headings
# never have a *space* right after the hyphen, so this is a safe signal.
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_GLUED_BULLET_RE = re.compile(r"(?<=\S)-(?=\s[A-Z]|\*\*)")


def fix_glued_headings(lines: list[str]) -> list[str]:
    out = []
    for line in lines:
        m = _HEADING_RE.match(line)
        if not m:
            out.append(line)
            continue
        hashes, text = m.group(1), m.group(2)
        gm = _GLUED_BULLET_RE.search(text)
        if gm:
            out.append(f"{hashes} {text[:gm.start()].rstrip()}")
            out.append(text[gm.start():])
        else:
            out.append(line)
    return out


# ---------------------------------------------------------------------------
# 5. Block-level parsing (paragraphs / lists / tables / blockquotes)
# ---------------------------------------------------------------------------

_BULLET_RE = re.compile(r"^(\s*)[-*]\s+(.*)$")
_NUM_RE = re.compile(r"^(\s*)\d+\.\s+(.*)$")
_TABLE_LINE_RE = re.compile(r"^\s*\|")
_SEP_CELL_RE = re.compile(r"^:?-+:?$")
_HR_RE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")


def _is_list_line(line: str) -> bool:
    return bool(_BULLET_RE.match(line) or _NUM_RE.match(line))


def tokenize_blocks(lines: list[str]):
    """Split a scope's raw lines into block tokens:
    ('heading', level, text) | ('blockquote', [lines]) | ('table', [lines])
    | ('list', [lines]) | ('para', text)
    Blank lines are separators and are dropped."""
    tokens = []
    i, n = 0, len(lines)
    para_buf: list[str] = []

    def flush_para():
        if para_buf:
            tokens.append(("para", " ".join(x.strip() for x in para_buf if x.strip())))
            para_buf.clear()

    while i < n:
        line = lines[i]
        stripped = line.strip()
        if stripped == "":
            flush_para()
            i += 1
            continue
        if _HR_RE.match(line):
            flush_para()
            tokens.append(("hr",))
            i += 1
            continue
        hm = _HEADING_RE.match(line)
        if hm:
            flush_para()
            tokens.append(("heading", len(hm.group(1)), hm.group(2).strip()))
            i += 1
            continue
        if line.lstrip().startswith(">"):
            flush_para()
            block = []
            while i < n and lines[i].lstrip().startswith(">"):
                block.append(lines[i])
                i += 1
            tokens.append(("blockquote", block))
            continue
        if _TABLE_LINE_RE.match(line):
            flush_para()
            block = []
            while i < n and _TABLE_LINE_RE.match(lines[i]):
                block.append(lines[i])
                i += 1
            tokens.append(("table", block))
            continue
        if _is_list_line(line):
            flush_para()
            block = []
            while i < n and lines[i].strip() != "" and _is_list_line(lines[i]):
                block.append(lines[i])
                i += 1
            tokens.append(("list", block))
            continue
        para_buf.append(line)
        i += 1
    flush_para()
    return tokens


def split_table_cells(line: str) -> list[str]:
    inner = line.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|"):
        inner = inner[:-1]
    return [c.strip() for c in inner.split("|")]


def parse_table(lines: list[str]) -> dict:
    rows_raw = [split_table_cells(l) for l in lines]

    def is_sep_row(cells):
        return all(_SEP_CELL_RE.match(c) for c in cells if c != "")

    header, aligns, data_start = None, None, 0
    if len(rows_raw) >= 2 and is_sep_row(rows_raw[1]):
        header, aligns, data_start = rows_raw[0], rows_raw[1], 2
    rows = rows_raw[data_start:]

    def proc_cell(c: str) -> str:
        c = c.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
        return convert_inline(c)

    out = {"type": "table", "rows": [[proc_cell(c) for c in r] for r in rows]}
    if header is not None and any(h.strip() for h in header):
        out["colLabels"] = [convert_inline(h) for h in header]
    if aligns:
        styles = []
        any_special = False
        for a in aligns:
            a = a.strip()
            if a.startswith(":") and a.endswith(":") and len(a) > 1:
                styles.append("text-center")
                any_special = True
            elif a.endswith(":"):
                styles.append("text-right")
                any_special = True
            else:
                styles.append("")
        if any_special:
            out["colStyles"] = styles
    return out


def parse_list(lines: list[str]) -> dict:
    items: list = []
    i, n = 0, len(lines)

    def indent_and_text(line):
        m = _BULLET_RE.match(line) or _NUM_RE.match(line)
        return len(m.group(1)), m.group(2)

    while i < n:
        ind, text = indent_and_text(lines[i])
        i += 1
        sub = []
        while i < n:
            ind2, _ = indent_and_text(lines[i])
            if ind2 > ind:
                sub.append(lines[i])
                i += 1
            else:
                break
        item_block = make_paragraph_entry(text)
        items.append(item_block)
        if sub:
            items.append(parse_list(sub))
    return {"type": "list", "items": items}


_QUOTE_ATTR_RE = re.compile(r"^(?P<quote>.*)\*?\s*—\s*(?P<attr>[^—]+)$", re.DOTALL)
_QUOTE_FULL_ITALIC_RE = re.compile(r"^\*(.+)\*$", re.DOTALL)
_ATTR_BOOK_RE = re.compile(r"^(?P<by>[^*]*?),?\s*\*(?P<from>[^*]+)\*\s*$")
_MULTI_SENTENCE_RE = re.compile(r"(?<![A-Z])[.!?]['\")]?\s+[A-Z]")


def _attribution_is_plausible(attr: str) -> bool:
    """Reject em-dash splits that are just dramatic mid-dialogue pauses
    (long, multi-sentence, lowercase-led continuations, or dialogue that
    simply ends with an exclamation/question) rather than a real
    "- Author, *Book*" citation, which is always short and name-shaped."""
    attr = attr.strip()
    if not attr or len(attr) > 100:
        return False
    if not re.match(r"^[A-Z*\"'\u2018\u201c]", attr):
        return False
    if re.search(r"[!?]\*?$", attr):
        return False
    if _MULTI_SENTENCE_RE.search(attr):
        return False
    return True


def _make_quote(flat_text: str):
    m = _QUOTE_ATTR_RE.match(flat_text.strip())
    if m and len(m.group("quote").strip()) > 8 and _attribution_is_plausible(m.group("attr")):
        quote_part = m.group("quote").strip()
        if quote_part.startswith("*"):
            quote_part = quote_part[1:]
        quote_part = quote_part.rstrip("*").strip()
        attr = m.group("attr").strip()
        bm = _ATTR_BOOK_RE.match(attr)
        out = {"type": "quote", "entries": [convert_inline(quote_part)]}
        if bm:
            by = bm.group("by").strip().rstrip(",").strip()
            if by:
                out["by"] = by
            out["from"] = bm.group("from").strip()
        elif attr:
            out["by"] = attr
        return out
    fm = _QUOTE_FULL_ITALIC_RE.match(flat_text.strip())
    if fm:
        return {"type": "quote", "entries": [convert_inline(fm.group(1).strip())]}
    return None


def parse_blockquote(lines: list[str]):
    # Normalize nesting depth: strip the minimum common number of leading
    # '>' markers shared by every non-blank line in this run.
    def depth_of(line):
        d = 0
        while d < len(line) and line[d] == ">":
            d += 1
        return d

    non_blank = [l for l in lines if l.strip(" >") != ""]
    min_depth = min((depth_of(l) for l in non_blank), default=1)
    dedented = []
    for l in lines:
        d = 0
        while d < min_depth and d < len(l) and l[d] == ">":
            d += 1
        rest = l[d:]
        if rest.startswith(" "):
            rest = rest[1:]
        dedented.append(rest)

    # Sidebar title: first non-blank line is itself a heading.
    first_idx = next((i for i, l in enumerate(dedented) if l.strip() != ""), None)
    name = None
    body_lines = dedented
    if first_idx is not None:
        hm = _HEADING_RE.match(dedented[first_idx])
        if hm:
            name = convert_inline(hm.group(2).strip())
            body_lines = dedented[:first_idx] + dedented[first_idx + 1:]

    if name is None:
        flat_tokens = tokenize_blocks(dedented)
        if len(flat_tokens) == 1 and flat_tokens[0][0] == "para":
            q = _make_quote(flat_tokens[0][1])
            if q:
                return q

    entries = build_entries_from_tokens(tokenize_blocks(body_lines))
    out_type = "insetReadaloud" if (name and re.search(r"read.?aloud", name, re.I)) else "inset"
    out = {"type": out_type, "entries": entries}
    if name:
        out["name"] = name
    return out


def make_paragraph_entry(raw_text: str):
    raw_text = raw_text.strip()
    if not raw_text:
        return ""
    if _EMBED_TAG_FULL_RE.match(raw_text):
        return raw_text
    leadin = split_bold_italic_leadin(raw_text)
    if leadin:
        name, rest = leadin
        rest_conv = convert_inline(rest) if rest else ""
        return {"type": "entries", "name": name, "entries": [rest_conv] if rest_conv else []}
    return convert_inline(raw_text)


def dedupe_and_finalize_embeds(blocks: list):
    """Collapse consecutive identical bare embed-tag paragraphs (the
    Fluff+Stats sibling-widget pattern) and promote whole-paragraph embed
    tags to `type:"statblock"` nodes where the schema supports it."""
    out = []
    last_key = None
    for b in blocks:
        if isinstance(b, str):
            m = _EMBED_TAG_FULL_RE.match(b.strip())
            if m:
                key = (m.group(1), m.group(2))
                if key == last_key:
                    continue
                last_key = key
                out.append(finalize_embed_paragraph(*key))
                continue
        last_key = None
        out.append(b)
    return out


def build_entries_from_tokens(tokens) -> list:
    """Convert a flat token list (as produced by tokenize_blocks) into the
    final JSON entries array. Headings encountered here (only possible
    inside recursively-parsed scopes such as blockquotes) become nameless-id
    nested `entries` wrappers - true top-level document headings never reach
    this function because the outer tree builder consumes them first."""
    blocks: list = []
    i, n = 0, len(tokens)
    while i < n:
        kind = tokens[i][0]
        if kind == "para":
            blocks.append(make_paragraph_entry(tokens[i][1]))
            i += 1
        elif kind == "table":
            blocks.append(parse_table(tokens[i][1]))
            i += 1
        elif kind == "list":
            blocks.append(parse_list(tokens[i][1]))
            i += 1
        elif kind == "blockquote":
            blocks.append(parse_blockquote(tokens[i][1]))
            i += 1
        elif kind == "hr":
            blocks.append({"type": "hr"})
            i += 1
        elif kind == "heading":
            level = tokens[i][1]
            name = convert_inline(tokens[i][2])
            i += 1
            sub = []
            while i < n and not (tokens[i][0] == "heading" and tokens[i][1] <= level):
                sub.append(tokens[i])
                i += 1
            blocks.append({"type": "entries", "name": name, "entries": build_entries_from_tokens(sub)})
        else:
            i += 1
    return dedupe_and_finalize_embeds(blocks)


# ---------------------------------------------------------------------------
# 6. Top-level heading tree (chapters/sections) + stable ids
# ---------------------------------------------------------------------------

_NON_SLUG_RE = re.compile(r"[^a-z0-9]+")
_TAG_STRIP_RE = re.compile(r"\{@\w+\s+([^{}|]+)(?:\|[^{}]*)?\}")


def slugify(text: str) -> str:
    text = _TAG_STRIP_RE.sub(r"\1", text)
    text = text.lower().replace("'", "").replace("\u2019", "")
    text = _NON_SLUG_RE.sub("-", text).strip("-")
    return text or "section"


class Node:
    __slots__ = ("level", "name", "children", "direct_lines", "id", "direct_entries")

    def __init__(self, level: int, name: str):
        self.level = level
        self.name = name
        self.children: list[Node] = []
        self.direct_lines: list[str] = []
        self.id: str | None = None
        self.direct_entries: list | None = None


def ensure_leading_chapter(lines: list[str], chapter_level: int, title: str) -> list[str]:
    first_idx = None
    for i, l in enumerate(lines):
        m = _HEADING_RE.match(l)
        if m and len(m.group(1)) == chapter_level:
            first_idx = i
            break
    if first_idx is None:
        return lines
    if any(l.strip() for l in lines[:first_idx]):
        return [("#" * chapter_level) + " " + title] + lines
    return lines


def build_tree(lines: list[str]) -> list[Node]:
    levels = [len(m.group(1)) for l in lines if (m := _HEADING_RE.match(l))]
    chapter_level = min(levels) if levels else 1
    roots: list[Node] = []
    stack: list[tuple[int, Node]] = []
    for line in lines:
        hm = _HEADING_RE.match(line)
        if not hm:
            if stack:
                stack[-1][1].direct_lines.append(line)
            continue
        level = len(hm.group(1))
        name = convert_inline(hm.group(2).strip())
        node = Node(level, name)
        while stack and stack[-1][0] >= level:
            stack.pop()
        if stack:
            stack[-1][1].children.append(node)
        else:
            roots.append(node)
        stack.append((level, node))
    return roots, chapter_level


def assign_ids(node: Node, parent_id: str, used: dict, is_root: bool = False):
    slug = slugify(node.name)
    n = used.get(slug, 0) + 1
    used[slug] = n
    if n > 1:
        slug = f"{slug}-{n}"
    node.id = f"{parent_id}:{slug}" if is_root else f"{parent_id}/{slug}"
    child_used: dict = {}
    for c in node.children:
        assign_ids(c, node.id, child_used)


def parse_node_direct_entries(node: Node):
    if node.direct_entries is None:
        node.direct_entries = build_entries_from_tokens(tokenize_blocks(node.direct_lines))
    return node.direct_entries


def serialize_node(node: Node, is_chapter: bool):
    direct = parse_node_direct_entries(node)
    children_ser = [serialize_node(c, False) for c in node.children]
    all_entries = list(direct) + children_ser
    if (not is_chapter and not node.children and len(direct) == 1
            and isinstance(direct[0], dict) and direct[0].get("type") in ("table", "list")):
        obj = dict(direct[0])
        obj["id"] = node.id
        if node.name:
            obj["caption" if obj["type"] == "table" else "name"] = node.name
        return obj
    out = {"type": "section" if is_chapter else "entries", "name": node.name, "id": node.id, "entries": all_entries}
    return out


def build_contents_entry(chapter: Node) -> dict:
    headers: list = []

    def walk(n: Node, depth: int):
        for c in n.children:
            headers.append(c.name if depth == 0 else {"header": c.name, "depth": depth})
            walk(c, depth + 1)

    walk(chapter, 0)
    out = {"name": chapter.name}
    if headers:
        out["headers"] = headers
    return out


# ---------------------------------------------------------------------------
# 7. sections.jsonl: category guessing
# ---------------------------------------------------------------------------

_TAG_REF_RE = re.compile(r"\{@([a-zA-Z]+)\s+([^{}|]+)(?:\|([^{}]*))?\}")

_TAG_TO_CATEGORY = {
    "creature": "monster", "item": "item", "spell": "spell", "feat": "feat",
    "race": "race", "background": "background", "class": "class-feature",
    "subclass": "class-feature", "optfeature": "class-feature",
    "deity": "deity", "table": "table", "vehicle": "vehicle",
    "object": "object", "trap": "trap-hazard", "hazard": "trap-hazard",
    "condition": "condition-disease", "disease": "condition-disease",
    "reward": "reward", "recipe": "recipe", "variantrule": "rules",
    "action": "rules", "language": "rules", "deck": "rules",
    "charoption": "race",
}

_CLASS_NAMES = {
    "barbarian", "bard", "cleric", "druid", "fighter", "monk", "paladin",
    "ranger", "rogue", "sorcerer", "warlock", "wizard", "artificer",
}
_RACE_CHAPTER_HINTS = {"races", "race", "species", "playable races", "lineages", "a world of new races"}
_BACKGROUND_CHAPTER_HINTS = {"backgrounds", "background"}
_DEITY_CHAPTER_HINTS = {"deities", "gods", "pantheon", "pantheons", "gods of the multiverse", "gods of the forgotten realms"}
_ITEM_CHAPTER_HINTS = {"magic items", "treasure", "wondrous items"}
_SPELL_CHAPTER_HINTS = {"spells", "spell descriptions", "spell lists", "new spells"}

_ITEM_RARITY_RE = re.compile(
    r"\b(wondrous item|potion|ring|rod|scroll|staff|wand|weapon \([^)]*\)|armor \([^)]*\)|"
    r"adventuring gear)\b[^.{}]{0,40}\b(common|uncommon|rare|very rare|legendary|artifact|varies)\b",
    re.I,
)
_SPELL_LEVEL_RE = re.compile(
    r"\b(cantrip|1st-level|2nd-level|3rd-level|[4-9]th-level)\b[^.{}]{0,40}\b"
    r"(abjuration|conjuration|divination|enchantment|evocation|illusion|necromancy|transmutation)\b",
    re.I,
)
_STATBLOCK_MARKER_RE = re.compile(r"\barmor class\b[^.]{0,30}\bhit points\b|\bchallenge\b\s+[\d/]", re.I)


def collect_strings(obj, out: list[str]):
    if isinstance(obj, str):
        if obj:
            out.append(obj)
    elif isinstance(obj, dict):
        if obj.get("name"):
            out.append(obj["name"])
        if obj.get("type") == "table":
            for row in obj.get("rows", []):
                for cell in row:
                    collect_strings(cell, out)
            for lbl in obj.get("colLabels", []):
                collect_strings(lbl, out)
        for key in ("entries", "items"):
            for v in obj.get(key, []) or []:
                collect_strings(v, out)
    elif isinstance(obj, list):
        for v in obj:
            collect_strings(v, out)


def guess_category(node: Node, ancestor_names: list[str], direct_entries: list, book_meta: dict):
    strings: list[str] = []
    collect_strings(direct_entries, strings)
    flat = " ".join(strings)
    flat_plain = _TAG_STRIP_RE.sub(r"\1", flat)

    refs = [(m.group(1), m.group(2).strip()) for m in _TAG_REF_RE.finditer(flat)]
    statblock_refs = [
        (b.get("tag"), b.get("name"))
        for b in (direct_entries if isinstance(direct_entries, list) else [])
        if isinstance(b, dict) and b.get("type") == "statblock"
    ]
    refs = refs + [r for r in statblock_refs if r[0] and r[1]]

    if refs:
        counts = Counter(t for t, _ in refs)
        top_tag, _ = counts.most_common(1)[0]
        category = _TAG_TO_CATEGORY.get(top_tag)
        if category:
            names = sorted({n for t, n in refs if t == top_tag})
            name_matches = node.name.lower() in {n.lower() for _, n in refs}
            confidence = "high" if (name_matches or len(refs) == 1) else "medium"
            return category, confidence, names[:15]

    low = flat_plain.lower()
    if _ITEM_RARITY_RE.search(low):
        return "item", "medium", [node.name]
    if _SPELL_LEVEL_RE.search(low) and "casting time" in low:
        return "spell", "high", [node.name]
    if re.search(r"\bprerequisite\b\s*:", low):
        return "feat", "medium", [node.name]
    if "alignment" in low and ("domain" in low or "symbol" in low):
        return "deity", "medium", [node.name]
    if "skill proficiencies" in low and ("tool proficiencies" in low or "equipment" in low or "languages" in low):
        return "background", "medium", [node.name]
    if _STATBLOCK_MARKER_RE.search(low):
        return "monster", "medium", [node.name]

    if (not node.children and len(direct_entries) == 1 and isinstance(direct_entries[0], dict)
            and direct_entries[0].get("type") == "table"):
        return "table", "medium", []

    anc_lower = [a.lower() for a in ancestor_names]
    if any(a in _CLASS_NAMES for a in anc_lower) or node.name.lower() in _CLASS_NAMES:
        return "class-feature", "low", [node.name]
    if any(a in _RACE_CHAPTER_HINTS for a in anc_lower):
        return "race", "low", [node.name]
    if any(a in _BACKGROUND_CHAPTER_HINTS for a in anc_lower):
        return "background", "low", [node.name]
    if any(a in _DEITY_CHAPTER_HINTS for a in anc_lower):
        return "deity", "low", [node.name]
    if any(a in _ITEM_CHAPTER_HINTS for a in anc_lower):
        return "item", "low", [node.name]
    if any(a in _SPELL_CHAPTER_HINTS for a in anc_lower):
        return "spell", "low", [node.name]

    return "lore", "low", []


def walk_sections(node: Node, source: str, ancestors: list[str], book_meta: dict, out_rows: list[dict]):
    direct = parse_node_direct_entries(node)

    def subtree_strings(n: Node):
        acc: list[str] = []
        collect_strings(parse_node_direct_entries(n), acc)
        for c in n.children:
            acc.extend(subtree_strings(c))
        return acc

    full_text = " ".join(subtree_strings(node))
    full_text_plain = _TAG_STRIP_RE.sub(r"\1", full_text)
    chars = len(full_text_plain)
    preview = full_text_plain[:200]

    category, confidence, entities_guess = guess_category(node, ancestors, direct, book_meta)

    out_rows.append({
        "id": node.id,
        "source": source,
        "heading": node.name,
        "path": ancestors + [node.name],
        "level": node.level,
        "chars": chars,
        "preview": preview,
        "category": category,
        "confidence": confidence,
        "entities_guess": entities_guess,
    })
    for c in node.children:
        walk_sections(c, source, ancestors + [node.name], book_meta, out_rows)


# ---------------------------------------------------------------------------
# 8. Per-book conversion driver
# ---------------------------------------------------------------------------

def count_tables_lists(obj, counts: Counter):
    if isinstance(obj, dict):
        t = obj.get("type")
        if t == "table":
            counts["tables"] += 1
        elif t == "list":
            counts["lists"] += 1
        elif t == "statblock":
            counts["statblocks"] += 1
        elif t == "quote":
            counts["quotes"] += 1
        elif t in ("inset", "insetReadaloud"):
            counts["insets"] += 1
        for key in ("entries", "items"):
            for v in obj.get(key, []) or []:
                count_tables_lists(v, counts)
        for row in obj.get("rows", []) or []:
            for cell in row:
                count_tables_lists(cell, counts)
    elif isinstance(obj, list):
        for v in obj:
            count_tables_lists(v, counts)


def convert_book(meta: dict) -> dict:
    path = BOOKS_DIR / meta["file"]
    raw = path.read_text(encoding="utf-8")
    text = strip_embed_divs(raw)
    text = html.unescape(text)
    lines = fix_glued_headings(text.split("\n"))

    chapters, chapter_level = build_tree(lines)
    if not chapters:
        chapters, chapter_level = build_tree(ensure_leading_chapter(lines, chapter_level, meta["full"]))
    else:
        # also handle the no-chapter-heading-at-all edge case (file whose
        # minimum heading level has leading non-heading content before it)
        lines2 = ensure_leading_chapter(lines, chapter_level, meta["full"])
        if lines2 is not lines:
            chapters, chapter_level = build_tree(lines2)

    used_top: dict = {}
    source = meta["source"]
    for ch in chapters:
        assign_ids(ch, source, used_top, is_root=True)

    book_index = {"name": meta["full"], "id": meta["id"], "source": source,
                  "group": meta["group"], "published": meta["published"],
                  "contents": [build_contents_entry(ch) for ch in chapters]}
    if meta["authors"]:
        book_index["author"] = meta["authors"][0] if len(meta["authors"]) == 1 else ", ".join(meta["authors"])

    data = [serialize_node(ch, True) for ch in chapters]

    sections: list[dict] = []
    for ch in chapters:
        walk_sections(ch, source, [], meta, sections)

    counts = Counter()
    for d in data:
        count_tables_lists(d, counts)
    counts["sections"] = len(sections)
    counts["chapters"] = len(chapters)

    kind = meta["kind"]
    index_key = "book" if kind == "book" else "adventure"
    data_key = "bookData" if kind == "book" else "adventureData"

    out_json = {
        "_meta": {
            "sources": [{
                "json": source,
                "abbreviation": source,
                "full": meta["full"],
                "version": "1.0.0",
                "dateReleased": meta["published"],
                "authors": meta["authors"],
            }],
            "edition": "classic",
            "dateAdded": GEN_TIME,
            "dateLastModified": GEN_TIME,
        },
        index_key: [book_index],
        data_key: [{"id": meta["id"], "source": source, "data": data}],
    }
    return {"json": out_json, "sections": sections, "counts": counts}


# ---------------------------------------------------------------------------
# 9. Main
# ---------------------------------------------------------------------------

def main():
    OUT_BOOKS_DIR.mkdir(parents=True, exist_ok=True)

    sources_doc = {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(GEN_TIME)),
        "note": ("All 51 files matched an existing official 5etools source code "
                 "(cross-checked against data/books.json in the 5etools-src repo); "
                 "none required an invented code, and none are classified as "
                 "adventures (that registry's adventures.json contains no titles "
                 "matching these 51 books)."),
        "uncertain": UNCERTAIN_BOOKS,
        "books": SOURCES,
    }
    SOURCES_JSON.write_text(json.dumps(sources_doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    all_sections: list[dict] = []
    per_book_counts: dict[str, Counter] = {}
    category_totals: Counter = Counter()
    confidence_totals: Counter = Counter()
    errors: list[tuple[str, str]] = []

    for meta in SOURCES:
        try:
            result = convert_book(meta)
        except Exception as exc:  # noqa: BLE001
            errors.append((meta["file"], f"{type(exc).__name__}: {exc}"))
            print(f"ERROR converting {meta['file']}: {exc}", file=sys.stderr)
            continue
        out_path = OUT_BOOKS_DIR / f"{meta['source']}.json"
        out_path.write_text(json.dumps(result["json"], indent="\t", ensure_ascii=False) + "\n", encoding="utf-8")
        per_book_counts[meta["source"]] = result["counts"]
        all_sections.extend(result["sections"])
        for row in result["sections"]:
            category_totals[row["category"]] += 1
            confidence_totals[row["confidence"]] += 1

    with SECTIONS_JSONL.open("w", encoding="utf-8") as fh:
        for row in all_sections:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"\nConverted {len(per_book_counts)}/{len(SOURCES)} books.")
    if errors:
        print(f"ERRORS ({len(errors)}):")
        for f, e in errors:
            print(f"  - {f}: {e}")

    print("\nPer-book counts (source: sections / chapters / tables / lists / insets / quotes / statblocks):")
    for meta in SOURCES:
        c = per_book_counts.get(meta["source"])
        if not c:
            continue
        print(f"  {meta['source']:20} {c['sections']:5} sect  {c['chapters']:3} chap  "
              f"{c['tables']:4} tbl  {c['lists']:4} list  {c['insets']:4} inset  "
              f"{c['quotes']:3} quote  {c['statblocks']:4} statblock")

    print(f"\nTotal sections.jsonl rows: {len(all_sections)}")
    print("Category guess counts (all books):")
    for cat, cnt in category_totals.most_common():
        print(f"  {cat:16} {cnt}")
    print("Confidence counts:")
    for conf, cnt in confidence_totals.most_common():
        print(f"  {conf:8} {cnt}")

    print(f"\nBooks with uncertain kind/source code: {UNCERTAIN_BOOKS or 'none'}")


if __name__ == "__main__":
    main()
