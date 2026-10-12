#!/usr/bin/env python3
"""Extract `spell` entities from the 51 official-book Markdown files into the
`spells` shard (ref/5etools/shards/spells/<SOURCE>.json).

--------------------------------------------------------------------------
Why this script does NOT parse prose spell stat blocks out of the Markdown
--------------------------------------------------------------------------
The source Markdown (ref/books/*.md) was scraped from the 5etools site. On
that site, every individual spell write-up (the "Level X school / Casting
Time / Range / Components / Duration" stat block + description) is rendered
by a client-side widget that transcludes the spell from the site's own spell
database, rather than being static chapter prose. The scrape did not execute
that JS, so across all 51 books the spell content collapses to one of:

  1. An empty "loading" placeholder stub, e.g. in the Markdown:
       <td ... data-rd-tag="spell" data-rd-name="Acid Splash"
           data-rd-source="PHB" data-rd-hash="acid%20splash_phb" ...>
         <i>Loading "<a ... data-vet-source="PHB" ...>Acid Splash</a>"...</i>
     (`data-rd-entry-data="{}"` is always empty -- verified across all 449
     stub instances in the corpus; zero contain real inline data.)
  2. A summary table (new-spell chapters in TCE/FTD/SCC/BMT/AAG/SatO):
       | Level | Spell | School | Conc. | Ritual | Class |
     with NO stat block/description anywhere else in the book (verified: each
     such spell's name appears exactly once in the whole document, in that
     table cell).
  3. A bare name in a class spell list (PHB "### Bard Spells" style) or an
     inline "Spell: *Name*" callout (GGR), again with no stat block text.

Grepping the entire corpus for the universal "(V, S" / "(V, S, M" spell
component signature returns zero hits, and for "Casting Time"/"at higher
levels" as stat-block labels returns zero (the handful of plain-prose hits
are generic rules explanations, not per-spell blocks). So a prose parser
alone would yield nothing for all 51 books.

Per project policy (see the numbered rules below) we instead resolve every
name we DO
find in the Markdown (stub / table row / class list / callout) against the
official 5etools data mirrored locally at ref/5etools-src/data/spells/, take
the spell's mechanics from there when that record's own `source` matches
the rule for the signal type, and record exactly where provenance came from
in a sidecar `<SOURCE>.provenance.json`. A genuine prose stat-block parser
(find_fulltext_spells + build_entity_from_fulltext) is still implemented and
run first for defensiveness/forward-compatibility; it finds zero matches in
the current corpus, which is consistent with the corpus-wide grep above.

--------------------------------------------------------------------------
Exact import rules applied (per instructions from Main)
--------------------------------------------------------------------------
  1. Where the Markdown contains a spell's full text, parse it (fulltext
     path). None found currently.
  2. Where the Markdown has only a *stub* (embed placeholder) for a spell:
       - if the stub's own data-rd-source equals this book's code: import,
         match="stub" (trivial reprint-of-self case: PHB, EGW, AI).
       - if the stub's data-rd-source is a DIFFERENT book, but this book
         gives the spell its own dedicated heading/section (a genuine
         reprint, not a passing mention): import under THIS book's source,
         using the matched record's mechanics, match="stub",
         dataFrom=<that other source>. Manually verified dedicated-section
         cases: RMR ("## Spells", reprints PHB spells under its own jokey
         spell-list chapter) and SCAG ("## Cantrips for Sorcerers,
         Warlocks, and Wizards", reprints TCE's blade cantrips).
       - if the stub is a passing mention inside unrelated running prose
         (no dedicated heading of its own): do NOT import; record as a
         cross-reference. Manually verified case: SAC (FAQ answers that
         cite existing spells as examples, e.g. "spells with the same
         timing as moonbeam: blade barrier, cloudkill, ...").
  3. Where a book lists its OWN new entities only in a summary table (or
     equivalent dedicated list/callout) and body text didn't survive the
     capture: import from ref/5etools-src when the matched record's own
     `source` field equals this book's code and the name matches exactly
     (case-insensitive). match="table-mention" (markdown table row) or
     "list-mention" (bullet list / "Spell: *Name*" callout). Never import
     a table/list mention whose matching record's source is a DIFFERENT
     book -- log those as cross-references instead. Names with no matching
     record anywhere are logged as not-converted.
  4. `page` is always omitted (no stable page numbers in this corpus), as
     are site-only fields not in the brew spell schema (`srd`,
     `basicRules`, fluff/foundry/roll20 fields, `classes` as given upstream
     -- see below).
  5. `classes.fromClassList` is NOT present on the upstream per-spell JSON
     records at all (verified: 0/18 spell files have a "classes" key on any
     entry) -- the site computes it separately. For stub-derived spells we
     reconstruct it from `ref/5etools-src/data/generated/
     gendata-spell-source-lookup.json` (the site's own precomputed
     name->classes reverse index). For table/list-derived spells we instead
     read the book's own "Class" column/text directly (more directly
     grounded in what *this* book states, and the generated lookup is
     frequently empty for these newer entries anyway).

Python 3.9 stdlib only. Run: python3 scripts/books/extract_spells.py
"""
from __future__ import annotations

import html
import json
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))
import structure_books as sb  # noqa: E402  (reuse wave-1 heading/slug/id logic verbatim)

BOOKS_DIR = REPO_ROOT / "ref" / "books"
BOOKS_JSON_DIR = REPO_ROOT / "ref" / "5etools" / "books"
SRC_DATA_DIR = REPO_ROOT / "ref" / "5etools-src" / "data"
SRC_SPELLS_DIR = SRC_DATA_DIR / "spells"
SRC_GENERATED_DIR = SRC_DATA_DIR / "generated"
OUT_DIR = REPO_ROOT / "ref" / "5etools" / "shards" / "spells"

GEN_TIME = int(time.time())

# Books where a stub whose data-rd-source differs from the book itself is
# still a genuine, dedicated reprint (its own heading/section), per manual
# inspection -- see module docstring rule 2.
CROSS_BOOK_STUB_OWN_ENTRY = {"RMR", "SCAG"}

SCHOOL_NAME_TO_CODE = {
    "abjuration": "A", "conjuration": "C", "divination": "D",
    "enchantment": "E", "evocation": "V", "illusion": "I",
    "necromancy": "N", "transmutation": "T", "psionic": "P", "psychic": "P",
}

CLASS_NAME_SOURCE = {"artificer": "TCE"}
DEFAULT_CLASS_SOURCE = "PHB"

# Fields copied verbatim from the matched official record (whitelist = the
# brew spells.json schema's own `spellData` properties, minus site-only /
# fluff / foundry / roll20 fields and minus `source`/`page`, which this
# project sets/omits itself).
ALLOWED_FIELDS = [
    "alias", "level", "school", "subschools", "meta", "time", "range",
    "components", "duration", "entries", "entriesHigherLevel",
    "additionalSources", "otherSources", "referenceSources", "reprintedAs",
    "damageInflict", "damageResist", "damageImmune", "damageVulnerable",
    "conditionInflict", "conditionImmune", "savingThrow", "abilityCheck",
    "spellAttack", "areaTags", "miscTags", "affectsCreatureType", "legacy",
    "scalingLevelDice", "groups",
]


# ---------------------------------------------------------------------------
# Official-data loading (ref/5etools-src/data/...)
# ---------------------------------------------------------------------------

def load_official_spells():
    """Returns (by_name_source, by_name):
    by_name_source: {(normalized_name, SOURCE): record}
    by_name: {normalized_name: [(SOURCE, record), ...]}  (all sources, for
       cross-reference resolution when a name isn't this book's own)
    """
    index = json.loads((SRC_SPELLS_DIR / "index.json").read_text(encoding="utf-8"))
    by_name_source = {}
    by_name = defaultdict(list)
    for _src_code, filename in index.items():
        fp = SRC_SPELLS_DIR / filename
        if not fp.exists():
            continue
        data = json.loads(fp.read_text(encoding="utf-8"))
        for rec in data.get("spell", []):
            if "_copy" in rec and "name" not in rec:
                continue
            name_key = normalize_name(rec["name"])
            by_name_source[(name_key, rec["source"])] = rec
            by_name[name_key].append((rec["source"], rec))
    return by_name_source, by_name


def load_class_lookup():
    fp = SRC_GENERATED_DIR / "gendata-spell-source-lookup.json"
    if not fp.exists():
        return {}
    return json.loads(fp.read_text(encoding="utf-8"))


def classes_from_lookup(lookup: dict, canonical_source: str, spell_name: str):
    entry = lookup.get(canonical_source.lower(), {}).get(normalize_name(spell_name))
    if not entry:
        return None
    cls = entry.get("class")
    if not cls:
        return None
    out, seen = [], set()
    for list_source, classes in cls.items():
        for cname in classes.keys():
            key = (cname, list_source)
            if key in seen:
                continue
            seen.add(key)
            out.append({"name": cname, "source": list_source})
    out.sort(key=lambda d: (d["source"], d["name"]))
    return out or None


_FOOTNOTE_RE = re.compile(r"^[*\u2020\u2021]+|[*\u2020\u2021]+$")


def classes_from_table_text(class_text: str):
    """Build classes.fromClassList directly from a book's own "Class" table
    column text (e.g. "Artificer,* Ranger, Sorcerer, Wizard" or "Sorcerer,
    warlock, wizard"). Preferred over the generated lookup for table/list
    -derived spells because it's literally what the book itself states."""
    if not class_text:
        return None
    out, seen = [], set()
    for raw in class_text.split(","):
        name = _FOOTNOTE_RE.sub("", raw.strip()).strip()
        if not name:
            continue
        name = name[:1].upper() + name[1:]
        source = CLASS_NAME_SOURCE.get(name.lower(), DEFAULT_CLASS_SOURCE)
        key = (name, source)
        if key in seen:
            continue
        seen.add(key)
        out.append({"name": name, "source": source})
    return out or None


def normalize_name(name: str) -> str:
    n = name.strip().lower()
    n = n.replace("\u2019", "'").replace("\u2018", "'")
    n = re.sub(r"\s+", " ", n)
    return n


def strip_self_source_refs(entity: dict, book_source: str) -> dict:
    """An entity we file under `book_source` shouldn't list that same book in
    fields that describe OTHER places the (upstream) spell also appears."""
    if "otherSources" in entity:
        kept = [x for x in entity["otherSources"] if x.get("source") != book_source]
        if kept:
            entity["otherSources"] = kept
        else:
            del entity["otherSources"]
    if "additionalSources" in entity:
        kept = [x for x in entity["additionalSources"] if x.get("source") != book_source]
        if kept:
            entity["additionalSources"] = kept
        else:
            del entity["additionalSources"]
    if "referenceSources" in entity:
        kept = [x for x in entity["referenceSources"] if x != book_source]
        if kept:
            entity["referenceSources"] = kept
        else:
            del entity["referenceSources"]
    if "reprintedAs" in entity:
        kept = [x for x in entity["reprintedAs"] if not x.endswith("|" + book_source)]
        if kept:
            entity["reprintedAs"] = kept
        else:
            del entity["reprintedAs"]
    return entity


def build_entity(rec: dict, book_source: str, class_lookup: dict,
                  canonical_source: str, table_class_text: str | None = None) -> dict:
    entity = {"name": rec["name"]}
    for k in ALLOWED_FIELDS:
        if k in rec:
            entity[k] = rec[k]
    entity["source"] = book_source
    entity = strip_self_source_refs(entity, book_source)
    if table_class_text:
        cls = classes_from_table_text(table_class_text)
    else:
        cls = classes_from_lookup(class_lookup, canonical_source, rec["name"])
    if cls:
        entity["classes"] = {"fromClassList": cls}
    return entity


# ---------------------------------------------------------------------------
# Markdown heading tree + section-id reconstruction (byte-identical to
# wave 1's sections.jsonl convention -- verified against known ids, e.g.
# "PHB:spells/spell-descriptions/a" for the "### A" alphabetical divider).
# ---------------------------------------------------------------------------

def _chapter_level(lines: list[str]) -> int:
    levels = [len(m.group(1)) for l in lines if (m := sb._HEADING_RE.match(l))]
    return min(levels) if levels else 1


def _build_tree_with_line_map(lines: list[str]):
    roots: list = []
    stack: list = []
    line_to_node = [None] * len(lines)
    for i, line in enumerate(lines):
        hm = sb._HEADING_RE.match(line)
        if not hm:
            if stack:
                line_to_node[i] = stack[-1][1]
            continue
        level = len(hm.group(1))
        name = sb.convert_inline(hm.group(2).strip())
        node = sb.Node(level, name)
        while stack and stack[-1][0] >= level:
            stack.pop()
        if stack:
            stack[-1][1].children.append(node)
        else:
            roots.append(node)
        stack.append((level, node))
        line_to_node[i] = node
    return roots, line_to_node


def build_tree_with_ids(text: str, meta: dict):
    """Returns (lines, line_to_node) where line_to_node[i].id is the exact
    section id wave 1 would have assigned to line i."""
    lines = sb.fix_glued_headings(text.split("\n"))
    chapters, line_to_node = _build_tree_with_line_map(lines)
    if not chapters:
        lines = sb.ensure_leading_chapter(lines, _chapter_level(lines), meta["full"])
        chapters, line_to_node = _build_tree_with_line_map(lines)
    else:
        lines2 = sb.ensure_leading_chapter(lines, _chapter_level(lines), meta["full"])
        if lines2 is not lines:
            lines = lines2
            chapters, line_to_node = _build_tree_with_line_map(lines)
    used_top: dict = {}
    for ch in chapters:
        sb.assign_ids(ch, meta["source"], used_top, is_root=True)
    return lines, line_to_node


def find_named_heading_id(lines: list[str], line_to_node: list, target_names: list[str]):
    """Best-effort fallback anchor: the id of the first heading whose text
    exactly matches one of `target_names` (case-insensitive), e.g. a book's
    own "Spells" chapter heading -- used only when a spell has no specific
    stub/table/list line to point the provenance sectionId at."""
    target_set = {t.lower() for t in target_names}
    for i, line in enumerate(lines):
        hm = sb._HEADING_RE.match(line)
        if not hm:
            continue
        name = sb.convert_inline(hm.group(2).strip())
        plain = sb._TAG_STRIP_RE.sub(r"\1", name).strip().lower()
        if plain in target_set:
            node = line_to_node[i]
            if node:
                return node.id
    return None


# ---------------------------------------------------------------------------
# Signal scanners
# ---------------------------------------------------------------------------

_STUB_TAG_RE = re.compile(r'<td[^>]*\bdata-rd-tag="spell"[^>]*>')
_ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')


def find_stub_mentions(lines: list[str]):
    out = []
    for i, line in enumerate(lines):
        if 'data-rd-tag="spell"' not in line:
            continue
        m = _STUB_TAG_RE.search(line)
        if not m:
            continue
        attrs = dict(_ATTR_RE.findall(m.group(0)))
        name = attrs.get("data-rd-name", "").strip()
        source = attrs.get("data-rd-source", "").strip()
        if name and source:
            out.append({"line": i, "name": name, "source": source})
    return out


def _split_table_row(line: str):
    s = line.strip()
    if not s.startswith("|"):
        return None
    return [c.strip() for c in s.strip("|").split("|")]


_SEP_CELL_RE = re.compile(r"^:?-+:?$")
_EMPH_TRIM_RE = re.compile(r"^[*_]+|[*_]+$")


def _strip_emph(cell: str) -> str:
    return _EMPH_TRIM_RE.sub("", cell.strip()).strip()


def find_table_mentions(lines: list[str]):
    """New-spell summary tables: a markdown table whose header row has both
    a "School" and a "Spell" column (TCE/FTD/SCC/BMT/AAG/SatO new-spell
    chapters)."""
    out = []
    n = len(lines)
    i = 0
    while i < n:
        cells = _split_table_row(lines[i])
        if cells:
            header = [c.lower() for c in cells]
            if "school" in header and "spell" in header and i + 1 < n:
                sep = _split_table_row(lines[i + 1])
                if sep and all(_SEP_CELL_RE.match(c) for c in sep if c):
                    name_idx = header.index("spell")
                    level_idx = header.index("level") if "level" in header else None
                    school_idx = header.index("school") if "school" in header else None
                    conc_idx = next((idx for idx, h in enumerate(header)
                                      if h.startswith("conc")), None)
                    ritual_idx = header.index("ritual") if "ritual" in header else None
                    class_idx = header.index("class") if "class" in header else None
                    j = i + 2
                    while j < n:
                        row = _split_table_row(lines[j])
                        if row is None:
                            break
                        if len(row) > name_idx:
                            name = _strip_emph(row[name_idx])
                            if name:
                                out.append({
                                    "line": j, "name": name,
                                    "level_text": row[level_idx].strip() if level_idx is not None and len(row) > level_idx else None,
                                    "school_text": row[school_idx].strip() if school_idx is not None and len(row) > school_idx else None,
                                    "conc_text": row[conc_idx].strip() if conc_idx is not None and len(row) > conc_idx else None,
                                    "ritual_text": row[ritual_idx].strip() if ritual_idx is not None and len(row) > ritual_idx else None,
                                    "class_text": row[class_idx].strip() if class_idx is not None and len(row) > class_idx else None,
                                })
                        j += 1
                    i = j
                    continue
        i += 1
    return out


_SPELL_CALLOUT_RE = re.compile(r"\bSpell:\s*\*([^*]+)\*")


def find_callout_mentions(lines: list[str]):
    """A deliberate authorial "Spell: *Name*" forward-reference callout
    (e.g. GGR's "(see 'Spell: *Encode Thoughts*' later in this section)"),
    distinct from an incidental italicized spell-name mention in running
    prose. Verified to match exactly one spell name in the whole 51-book
    corpus (GGR's Encode Thoughts)."""
    out = []
    for i, line in enumerate(lines):
        for m in _SPELL_CALLOUT_RE.finditer(line):
            name = m.group(1).strip()
            if name:
                out.append({"line": i, "name": name})
    return out


# ---------------------------------------------------------------------------
# Genuine full-text spell stat-block parser.
#
# Matches the standard format described by the PHB itself ("Each spell
# description ... begins with a block of information, including the spell's
# name, level, school of magic, casting time, range, components, and
# duration."): a heading, then an italicized "*Nth-level school (ritual)*"
# or "*School cantrip*" line, then bold-labelled Casting Time/Range/
# Components/Duration, then body prose, then an optional "***At Higher
# Levels.***" paragraph. A corpus-wide grep for the universal "(V, S"/
# "(V, S, M" component signature and for bold "Casting Time"/"Range"/
# "Duration" labels returns zero hits outside this file's own generic rules
# explanations, so this is expected to match nothing in the current corpus
# -- it exists for correctness/forward-compatibility, not because it's
# exercised today.
# ---------------------------------------------------------------------------

_LEVEL_SCHOOL_RE = re.compile(
    r"^\*(?:(\d+)(?:st|nd|rd|th)-level\s+([A-Za-z][A-Za-z ]*?)"
    r"|([A-Za-z][A-Za-z ]*?)\s+cantrip)(\s*\(ritual\))?\*\s*$",
    re.IGNORECASE,
)
_BOLD_LABEL_RE = re.compile(r"\*\*([^*]+?):\*\*\s*(.*)")


def find_fulltext_spells(lines: list[str]):
    """Detect+parse real prose spell stat blocks. See module docstring."""
    out = []
    n = len(lines)
    for i, line in enumerate(lines):
        hm = sb._HEADING_RE.match(line)
        if not hm:
            continue
        heading_name = sb.convert_inline(hm.group(2).strip())
        plain_name = sb._TAG_STRIP_RE.sub(r"\1", heading_name).strip()
        j = i + 1
        while j < n and not lines[j].strip():
            j += 1
        if j >= n:
            continue
        lm = _LEVEL_SCHOOL_RE.match(lines[j].strip())
        if not lm:
            continue
        level_txt = lm.group(1)
        school_txt = (lm.group(2) or lm.group(3) or "").strip().lower()
        is_ritual = bool(lm.group(4))
        labels = {}
        k = j + 1
        blank_run = 0
        body_start = None
        while k < n and k < j + 12:
            s = lines[k].strip()
            if not s:
                blank_run += 1
                if blank_run > 2:
                    break
                k += 1
                continue
            blank_run = 0
            bm = _BOLD_LABEL_RE.match(s)
            if bm:
                labels[bm.group(1).strip().lower()] = bm.group(2).strip()
                k += 1
                continue
            body_start = k
            break
        required = {"casting time", "range", "components", "duration"}
        if not required.issubset(labels.keys()):
            continue
        entries, hl_entries = [], []
        k = body_start if body_start is not None else k
        target = entries
        while k < n:
            s = lines[k]
            if sb._HEADING_RE.match(s):
                break
            st = s.strip()
            if not st:
                k += 1
                continue
            lead = split_bold_italic_leadin_at_higher_levels(st)
            if lead is not None:
                target = hl_entries
                st = lead
            target.append(apply_entry_tags(sb.convert_inline(st)))
            k += 1
        level = 0 if level_txt is None else int(level_txt)
        school_code = SCHOOL_NAME_TO_CODE.get(school_txt)
        if school_code is None:
            continue
        out.append({
            "heading_line": i, "name": plain_name, "level": level,
            "school": school_code, "ritual": is_ritual,
            "time": parse_time(labels["casting time"]),
            "range": parse_range(labels["range"]),
            "components": parse_components(labels["components"]),
            "duration": parse_duration(labels["duration"]),
            "entries": entries, "entriesHigherLevel": hl_entries,
        })
    return out


_AT_HIGHER_LEVELS_RE = re.compile(r"^\*\*\*at higher levels\.?\*\*\*\s*(.*)$", re.IGNORECASE)


def split_bold_italic_leadin_at_higher_levels(text: str):
    m = _AT_HIGHER_LEVELS_RE.match(text)
    return m.group(1).strip() if m else None


def parse_time(text: str):
    t = text.strip()
    m = re.match(r"^(\d+)\s+(action|bonus action|reaction|minute|hour|round)s?\b(.*)$", t, re.IGNORECASE)
    if m:
        unit = m.group(2).lower()
        if unit == "bonus action":
            unit = "bonus"
        rest = m.group(3).strip(" ,.")
        entry = {"number": int(m.group(1)), "unit": unit}
        if rest:
            entry["condition"] = rest
        return [entry]
    return [{"number": 1, "unit": "action", "note": t}]


_RANGE_SPECIAL_WORDS = {"self": "self", "touch": "touch", "sight": "sight", "unlimited": "unlimited"}


def parse_range(text: str):
    t = text.strip()
    m = re.match(r"^self\s*\((\d+)[- ]foot[- ](cone|cube|line|sphere|radius|hemisphere|cylinder|emanation)\)$", t, re.IGNORECASE)
    if m:
        return {"type": m.group(2).lower(), "distance": {"type": "feet", "amount": int(m.group(1))}}
    low = t.lower()
    if low in _RANGE_SPECIAL_WORDS:
        return {"type": "point", "distance": {"type": _RANGE_SPECIAL_WORDS[low]}}
    m = re.match(r"^(\d+)\s*feet$", t, re.IGNORECASE)
    if m:
        return {"type": "point", "distance": {"type": "feet", "amount": int(m.group(1))}}
    m = re.match(r"^(\d+)\s*miles?$", t, re.IGNORECASE)
    if m:
        return {"type": "point", "distance": {"type": "miles", "amount": int(m.group(1))}}
    return {"type": "special"}


def parse_components(text: str):
    comp: dict = {}
    m = re.match(r"^(.*?)\(([^)]*)\)\s*$", text.strip())
    main, material_text = (m.group(1), m.group(2)) if m else (text, None)
    parts = [p.strip().upper() for p in main.split(",") if p.strip()]
    if "V" in parts:
        comp["v"] = True
    if "S" in parts:
        comp["s"] = True
    if "M" in parts:
        if material_text:
            cost_m = re.search(r"worth at least (\d+)\s*gp", material_text, re.IGNORECASE)
            consumed = "consume" in material_text.lower() or "which the spell consumes" in material_text.lower()
            if cost_m:
                comp["m"] = {"text": material_text, "cost": int(cost_m.group(1)) * 100}
                if consumed:
                    comp["m"]["consume"] = True
            else:
                comp["m"] = material_text
        else:
            comp["m"] = True
    return comp


def parse_duration(text: str):
    t = text.strip()
    if re.match(r"^instantaneous$", t, re.IGNORECASE):
        return [{"type": "instant"}]
    if re.match(r"^until dispelled$", t, re.IGNORECASE):
        return [{"type": "permanent", "ends": ["dispel"]}]
    if re.match(r"^until dispelled or triggered$", t, re.IGNORECASE):
        return [{"type": "permanent", "ends": ["dispel", "trigger"]}]
    m = re.match(r"^concentration,?\s*up to\s*(\d+)\s*(round|minute|hour|day)s?$", t, re.IGNORECASE)
    if m:
        return [{"type": "timed", "duration": {"type": m.group(2).lower(), "amount": int(m.group(1)), "upTo": True}, "concentration": True}]
    m = re.match(r"^(\d+)\s*(round|minute|hour|day)s?$", t, re.IGNORECASE)
    if m:
        return [{"type": "timed", "duration": {"type": m.group(2).lower(), "amount": int(m.group(1))}}]
    return [{"type": "special"}]


_CONDITIONS = ["blinded", "charmed", "deafened", "frightened", "grappled",
               "incapacitated", "invisible", "paralyzed", "petrified",
               "poisoned", "prone", "restrained", "stunned", "unconscious",
               "exhaustion"]
_COND_RE = re.compile(r"\b(" + "|".join(_CONDITIONS) + r")\b", re.IGNORECASE)
_DICE_RE = re.compile(r"\b(\d+d\d+(?:\s*[+-]\s*\d+)?)\b")
_DC_RE = re.compile(r"\bDC\s*(\d+)\b")


def apply_entry_tags(text: str) -> str:
    text = _DC_RE.sub(lambda m: "{@dc %s}" % m.group(1), text)

    def dice_sub(m):
        window = (text[max(0, m.start() - 25):m.start()] + " " +
                   text[m.end():m.end() + 20]).lower()
        tag = "damage" if "damage" in window else "dice"
        return "{@%s %s}" % (tag, m.group(1).replace(" ", ""))
    text = _DICE_RE.sub(dice_sub, text)
    text = _COND_RE.sub(lambda m: "{@condition %s}" % m.group(1).lower(), text)
    return text


def build_entity_from_fulltext(parsed: dict, book_source: str) -> dict:
    entity = {
        "name": parsed["name"], "level": parsed["level"], "school": parsed["school"],
        "time": parsed["time"], "range": parsed["range"],
        "components": parsed["components"], "duration": parsed["duration"],
        "entries": parsed["entries"], "source": book_source,
    }
    if parsed["ritual"]:
        entity["meta"] = {"ritual": True}
    if parsed["entriesHigherLevel"]:
        entity["entriesHigherLevel"] = parsed["entriesHigherLevel"]
    return entity


# ---------------------------------------------------------------------------
# Per-book processing
# ---------------------------------------------------------------------------

def process_book(meta: dict, by_name_source: dict, by_name: dict, class_lookup: dict):
    source = meta["source"]
    path = BOOKS_DIR / meta["file"]
    if not path.exists():
        return None
    raw = path.read_text(encoding="utf-8")
    text = html.unescape(raw)
    lines, line_to_node = build_tree_with_ids(text, meta)

    def section_id_for(line_idx: int) -> str:
        node = line_to_node[line_idx] if 0 <= line_idx < len(line_to_node) else None
        return node.id if node else f"{source}:unknown"

    stub_mentions = find_stub_mentions(lines)
    table_mentions = find_table_mentions(lines)
    callout_mentions = find_callout_mentions(lines)
    fulltext_mentions = find_fulltext_spells(lines)

    resolved: dict = {}
    provenance: dict = {}
    cross_refs: dict = {}
    not_converted: list = []
    mismatches: list = []

    # 1. Full text (defensive path; see module docstring -- expected empty).
    for m in fulltext_mentions:
        name_key = normalize_name(m["name"])
        if name_key in resolved:
            continue
        entity = build_entity_from_fulltext(m, source)
        resolved[name_key] = entity
        provenance[entity["name"]] = {"origin": "markdown", "match": "text",
                                       "sectionId": section_id_for(m["heading_line"])}

    # 2. Stubs.
    for m in stub_mentions:
        name_key = normalize_name(m["name"])
        if name_key in resolved:
            continue
        stub_source = m["source"]
        if stub_source == source:
            rec = by_name_source.get((name_key, source))
            if rec is None:
                not_converted.append({"name": m["name"], "signal": "stub",
                                       "reason": f"stub pointed at source {stub_source} (this book) "
                                                 "but no matching record found in ref/5etools-src",
                                       "sectionId": section_id_for(m["line"])})
                continue
            entity = build_entity(rec, source, class_lookup, source)
            resolved[name_key] = entity
            provenance[rec["name"]] = {"origin": "5etools-src", "match": "stub",
                                        "sectionId": section_id_for(m["line"])}
        elif source in CROSS_BOOK_STUB_OWN_ENTRY:
            rec = by_name_source.get((name_key, stub_source))
            if rec is None:
                not_converted.append({"name": m["name"], "signal": "stub",
                                       "reason": f"stub pointed at source {stub_source} but no "
                                                 "matching record found in ref/5etools-src",
                                       "sectionId": section_id_for(m["line"])})
                continue
            entity = build_entity(rec, source, class_lookup, stub_source)
            resolved[name_key] = entity
            provenance[rec["name"]] = {"origin": "5etools-src", "match": "stub",
                                        "dataFrom": stub_source,
                                        "sectionId": section_id_for(m["line"])}
        else:
            rec = by_name_source.get((name_key, stub_source))
            display_name = rec["name"] if rec else m["name"]
            cross_refs.setdefault(display_name, {
                "sectionId": section_id_for(m["line"]),
                "pointsTo": {"name": display_name, "source": stub_source},
                "reason": "stub is a passing mention in running prose, not a dedicated reprint",
            })

    # 3. Table rows + callouts ("list-mention" / "table-mention").
    combined = [(m, "table-mention") for m in table_mentions] + \
               [(m, "list-mention") for m in callout_mentions]
    for m, match_kind in combined:
        name_key = normalize_name(m["name"])
        if name_key in resolved:
            continue
        rec = by_name_source.get((name_key, source))
        if rec is not None:
            entity = build_entity(rec, source, class_lookup, source,
                                   table_class_text=m.get("class_text"))
            resolved[name_key] = entity
            provenance[rec["name"]] = {"origin": "5etools-src", "match": match_kind,
                                        "sectionId": section_id_for(m["line"])}
            check_table_mismatch(m, rec, mismatches)
            continue
        others = by_name.get(name_key)
        if others:
            other_source, other_rec = others[0]
            cross_refs.setdefault(other_rec["name"], {
                "sectionId": section_id_for(m["line"]),
                "pointsTo": {"name": other_rec["name"], "source": other_source},
                "reason": f"{match_kind} names a spell whose only matching 5etools-src "
                          f"record is sourced to {other_source}, not this book",
            })
        else:
            not_converted.append({"name": m["name"], "signal": match_kind,
                                   "reason": "no matching 5etools-src record found under any source",
                                   "sectionId": section_id_for(m["line"])})

    # 4. Source-complete sweep (per Main's follow-up instruction, after the
    # XGE case): an official record whose own `source` exactly equals this
    # book's code is this book's content even when no stub/table/list
    # signal survived the Markdown capture at all (XGE's "Spells" chapter
    # collapsed to a single pointer sentence with zero per-spell text,
    # name, or stub). Import anything not already resolved above; point the
    # sectionId at a "Spells"-titled heading if this book has one, else a
    # generic per-book fallback, since there's no specific line to anchor to.
    source_complete_names = [rec["name"] for (name_key, rec_source), rec in by_name_source.items()
                              if rec_source == source and name_key not in resolved]
    if source_complete_names:
        fallback_section = (find_named_heading_id(lines, line_to_node, ["spells"])
                             or f"{source}:unknown")
        for name in source_complete_names:
            rec = by_name_source[(normalize_name(name), source)]
            entity = build_entity(rec, source, class_lookup, source)
            resolved[normalize_name(name)] = entity
            provenance[rec["name"]] = {"origin": "5etools-src", "match": "source-complete",
                                        "sectionId": fallback_section}
    return {
        "source": source,
        "entities": list(resolved.values()),
        "provenance": provenance,
        "cross_refs": cross_refs,
        "not_converted": not_converted,
        "mismatches": mismatches,
        "signal_counts": {"stub": len(stub_mentions), "table": len(table_mentions),
                           "callout": len(callout_mentions), "fulltext": len(fulltext_mentions)},
    }


def check_table_mismatch(m: dict, rec: dict, mismatches: list):
    """Sanity cross-check: does the book's own table row agree with the
    matched official record on level/school? Purely diagnostic (reported,
    never blocks conversion -- the official record is still used as-is)."""
    level_txt = (m.get("level_text") or "").strip().lower()
    level_num = {"0": 0, "cantrip": 0}.get(level_txt)
    if level_num is None:
        lm = re.match(r"^(\d+)(st|nd|rd|th)$", level_txt)
        if lm:
            level_num = int(lm.group(1))
    if level_num is not None and level_num != rec.get("level"):
        mismatches.append(f"{rec['name']}: table level {m.get('level_text')!r} vs "
                           f"record level {rec.get('level')!r}")
    school_txt = (m.get("school_text") or "").strip().lower()
    school_code = SCHOOL_NAME_TO_CODE.get(school_txt)
    if school_code is not None and school_code != rec.get("school"):
        mismatches.append(f"{rec['name']}: table school {m.get('school_text')!r} vs "
                           f"record school {rec.get('school')!r}")


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def load_book_meta_sources(source: str):
    fp = BOOKS_JSON_DIR / f"{source}.json"
    doc = json.loads(fp.read_text(encoding="utf-8"))
    return doc["_meta"]["sources"]


def write_shard(source: str, entities: list):
    if not entities:
        return
    out = {
        "_meta": {
            "sources": load_book_meta_sources(source),
            "edition": "classic",
            "dateAdded": GEN_TIME,
            "dateLastModified": GEN_TIME,
        },
        "spell": entities,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{source}.json").write_text(
        json.dumps(out, indent="\t", ensure_ascii=False) + "\n", encoding="utf-8")


def write_provenance(source: str, provenance: dict, cross_refs: dict, not_converted: list):
    if not provenance and not cross_refs and not not_converted:
        return
    doc = dict(sorted(provenance.items()))
    if cross_refs:
        doc["_crossReferences"] = dict(sorted(cross_refs.items()))
    if not_converted:
        doc["_notConverted"] = not_converted
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{source}.provenance.json").write_text(
        json.dumps(doc, indent="\t", ensure_ascii=False) + "\n", encoding="utf-8")


def main():
    by_name_source, by_name = load_official_spells()
    class_lookup = load_class_lookup()

    report = {"generated": GEN_TIME, "books": {}, "totals": Counter()}
    for meta in sb.SOURCES:
        result = process_book(meta, by_name_source, by_name, class_lookup)
        if result is None:
            print(f"WARNING: missing book file for {meta['source']}", file=sys.stderr)
            continue
        write_shard(result["source"], result["entities"])
        write_provenance(result["source"], result["provenance"],
                          result["cross_refs"], result["not_converted"])
        report["books"][result["source"]] = {
            "converted": len(result["entities"]),
            "cross_references": len(result["cross_refs"]),
            "not_converted": len(result["not_converted"]),
            "signal_counts": result["signal_counts"],
            "mismatches": result["mismatches"],
        }
        report["totals"]["converted"] += len(result["entities"])
        report["totals"]["cross_references"] += len(result["cross_refs"])
        report["totals"]["not_converted"] += len(result["not_converted"])
        for k, v in result["signal_counts"].items():
            report["totals"][f"signal_{k}"] += v

    report["books"] = {k: v for k, v in report["books"].items() if any([
        v["converted"], v["cross_references"], v["not_converted"],
        any(v["signal_counts"].values()),
    ])}
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
