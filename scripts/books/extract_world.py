#!/usr/bin/env python3
"""Extract `world` shard entities (deity, table, vehicle, object, trap, hazard,
condition, disease, status, reward, variantrule, language, cult, deck, card,
psionic, action) from every ref/5etools/books/<SOURCE>.json into
ref/5etools/shards/world/<SOURCE>.json (+ a provenance sidecar per book).

Python 3.9 stdlib only. Run: python3 scripts/books/extract_world.py

-------------------------------------------------------------------------
Method (see final report for the full rationale)
-------------------------------------------------------------------------
Wave 1 (`structure_books.py`) already turned every book's Markdown into a
schema-shaped heading tree (`ref/5etools/books/<SOURCE>.json`). About 40/51
books were originally scraped from the *live* 5etools site, which embeds
most entity references (conditions, actions, spells, deities, ...) as
"loading..." placeholder widgets rather than literal prose - wave 1
reconstructs those into `{"type":"statblock","tag":...,"name":...,
"source":...}` reference nodes (or, when glued into running prose, a bare
`{@tag name|source}` string). This means a large fraction of "does this
book define entity X" questions can't be answered from prose alone.

Per project-lead policy, this script treats `ref/5etools-src/data/*.json`
(a local sparse clone of the real 5etools database) as the authoritative
source for official content:
  1. If a book's own Markdown has REAL prose for an entity (a heading, or a
     table/list row, whose content is actual descriptive text), that prose
     is used (`origin: "markdown"`).
  2. If a book only has a placeholder/stub, or lists an entity by name in a
     table/list with no body text, the entity's data is copied from
     ref/5etools-src (`origin: "5etools-src"`), but the entity's `source`
     field is always set to THIS book (the book "owns" it because it has a
     dedicated heading/entry for it) - `data_from` in the provenance
     sidecar records which source the actual data came from.
  3. A bare in-sentence mention (not its own heading/stub/list row) is a
     cross-reference only and is never promoted to a standalone entity.
  4. Table-mention imports (rule in (2) with no stub, just a name in a
     list/table) only happen when the 5etools-src record's own `source`
     equals the book being processed (never cross-book on a bare mention).

Every candidate entity name processed by this script comes from
ref/5etools-src's own catalogue of records whose `source` matches one of
our 51 book codes - i.e. the work list is "what does the official database
say this book contains", cross-checked against our Markdown for textual
evidence before extraction. This keeps scope bounded and grounded at the
same time.
"""
from __future__ import annotations

import json
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BOOKS_DIR = REPO_ROOT / "ref" / "5etools" / "books"
SOURCES_JSON = REPO_ROOT / "ref" / "5etools" / "sources.json"
SRC_DATA_DIR = REPO_ROOT / "ref" / "5etools-src" / "data"
BREW_SCHEMA_DIR = REPO_ROOT / "ref" / "5etools" / "tooling" / "node_modules" / "5etools-utils" / "schema" / "brew"
OUT_DIR = REPO_ROOT / "ref" / "5etools" / "shards" / "world"

GEN_TIME = int(time.time())

# ---------------------------------------------------------------------------
# My assigned 5etools entity types and which ref/5etools-src/data file+array
# each one's canonical records live in.
# ---------------------------------------------------------------------------
MY_TAGS = [
    "action", "condition", "disease", "status", "deity", "object", "trap",
    "hazard", "reward", "variantrule", "language", "cult", "deck", "card",
    "psionic", "table", "vehicle",
]

TAG_TO_FILE_ARRAY = {
    "action": ("actions.json", "action"),
    "condition": ("conditionsdiseases.json", "condition"),
    "disease": ("conditionsdiseases.json", "disease"),
    "status": ("conditionsdiseases.json", "status"),
    "deity": ("deities.json", "deity"),
    "object": ("objects.json", "object"),
    "trap": ("trapshazards.json", "trap"),
    "hazard": ("trapshazards.json", "hazard"),
    "reward": ("rewards.json", "reward"),
    "variantrule": ("variantrules.json", "variantrule"),
    "language": ("languages.json", "language"),
    "cult": ("cultsboons.json", "cult"),
    "deck": ("decks.json", "deck"),
    "card": ("decks.json", "card"),
    "psionic": ("psionics.json", "psionic"),
    "table": ("tables.json", "table"),
    "vehicle": ("vehicles.json", "vehicle"),
}

VEHICLE_SUBTYPES = [
    "vehicleShip", "vehicleSpelljammer", "vehicleElementalAirship",
    "vehicleInfernalWarMachine", "vehicleCreature", "vehicleObject",
]

# Types whose schema shape is dominated by structured/numeric stat fields
# (hull/AC/HP/weapon blocks) rather than prose - for these we never try to
# reconstruct the entity from a Markdown heading's narrative text (which is
# flavor only and doesn't contain the mechanical data), even when such a
# heading exists. We always take the full record from ref/5etools-src once
# its presence in this book is confirmed by *some* textual evidence.
STATS_DOMINANT_TAGS = {"vehicle", "object"}

# Per-book overrides where generic heading-matching is known (from manual
# research) to collide with unrelated same-named content. BMT's 22 chapters
# are each titled after a classic "Deck of Many Things" card (Fool, Key,
# Balance, ...) but their content is thematic adventure material, not the
# card's own text (confirmed: BMT has no per-card prose for any of its 110
# cards anywhere - see final report) - and some of those same words recur
# as unrelated content elsewhere in the book (e.g. "Balance" is also a
# zodiac-sign heading). Always source BMT's cards from ref/5etools-src.
CARD_FORCE_SRC_BOOKS = {"BMT"}

ALIGNMENT_CHARS = set("LNCGEUA")

# ---------------------------------------------------------------------------
# Schema introspection: compute the set of property names the LOCAL brew
# schema allows for a given top-level type, so that anything copied wholesale
# from ref/5etools-src (which may be newer/richer than our vendored schema)
# gets filtered down to what will actually validate.
# ---------------------------------------------------------------------------
_schema_cache: dict[str, dict] = {}


def load_schema(fn: str) -> dict:
    if fn not in _schema_cache:
        _schema_cache[fn] = json.loads((BREW_SCHEMA_DIR / fn).read_text(encoding="utf-8"))
    return _schema_cache[fn]


def _resolve_ref(ref: str, current_file: str):
    if "#" in ref:
        file_part, path_part = ref.split("#", 1)
    else:
        file_part, path_part = ref, ""
    fn = file_part if file_part else current_file
    node = load_schema(fn)
    if path_part:
        for part in path_part.strip("/").split("/"):
            node = node[part]
    return node, fn


def _allowed_keys_for(fn: str, defname: str) -> set:
    """Union of property names across every non-`_copy` anyOf/oneOf arm of
    $defs[defname] in schema file `fn` (following $ref across files)."""
    node = load_schema(fn)["$defs"][defname]
    names: set = set()

    def walk(n, curfile):
        if not isinstance(n, dict):
            return
        if "$ref" in n and len(n) == 1:
            target, tfile = _resolve_ref(n["$ref"], curfile)
            walk(target, tfile)
            return
        if "properties" in n:
            props = n["properties"]
            if "_copy" in props and len(props) <= 3:
                return
            names.update(props.keys())
        for comb in ("anyOf", "oneOf", "allOf"):
            if comb in n:
                for sub in n[comb]:
                    walk(sub, curfile)

    walk(node, fn)
    return names


_ALLOWED_KEYS_CACHE: dict[str, set] = {}


def allowed_keys(tag: str) -> set:
    if tag not in _ALLOWED_KEYS_CACHE:
        fn, arr = TAG_TO_FILE_ARRAY[tag]
        _ALLOWED_KEYS_CACHE[tag] = _allowed_keys_for(fn, arr)
    return _ALLOWED_KEYS_CACHE[tag]


_VEHICLE_SUBTYPE_KEYS: dict[str, set] = {}


def vehicle_subtype_keys(subtype: str) -> set:
    if subtype not in _VEHICLE_SUBTYPE_KEYS:
        _VEHICLE_SUBTYPE_KEYS[subtype] = _allowed_keys_for("vehicles.json", subtype)
    return _VEHICLE_SUBTYPE_KEYS[subtype]


# Fields we never want to carry over from an external (ref/5etools-src or a
# different source book's) record even if the local schema allows them:
# page numbers refer to a different physical book, cross-source/reprint
# bookkeeping is meaningless once we've re-sourced the entity, and
# Foundry/token/image fields are VTT-integration plumbing outside scope.
DENY_FIELDS = {
    "page", "otherSources", "referenceSources", "reprintedAs", "legacy",
    "hasToken", "token", "tokenCredit", "tokenCustom", "tokenHref",
    "tokenHref3d", "tokenUrl", "altArt", "foundryImg", "foundryAdvice",
    "foundrySystem", "foundryActivities", "foundryFlags", "foundryEffects",
    "_foundryMerge", "foundryTokenScale", "foundryTokenSubjectHref",
    "foundryTokenSubjectScale", "srd", "srd52", "basicRules", "basicRules2024",
    "additionalSources", "reprintAlias",
}


def filter_record(tag: str, record: dict, name: str, source: str, subtype_keys=None) -> dict:
    keys = subtype_keys if subtype_keys is not None else allowed_keys(tag)
    out = {k: v for k, v in record.items() if k in keys and k not in DENY_FIELDS}
    out["name"] = name
    out["source"] = source
    return out


# ---------------------------------------------------------------------------
# ref/5etools-src resolver: canonical official data, used (a) as the content
# source when our own Markdown is stub-only, and (b) as the metadata source
# for structured fields even when our Markdown gives us the prose.
# ---------------------------------------------------------------------------
_src_cache: dict[str, dict] = {}


def load_src(fn: str) -> dict:
    if fn not in _src_cache:
        _src_cache[fn] = json.loads((SRC_DATA_DIR / fn).read_text(encoding="utf-8"))
    return _src_cache[fn]


_src_index_cache: dict[str, dict] = {}


def _src_index(tag: str) -> dict:
    if tag not in _src_index_cache:
        fn, arr = TAG_TO_FILE_ARRAY[tag]
        data = load_src(fn)
        idx: dict = {}
        for rec in data.get(arr, []):
            if "name" not in rec:
                continue
            key = (rec["name"].strip().lower(), str(rec.get("source", "")).strip().lower())
            idx.setdefault(key, []).append(rec)
        _src_index_cache[tag] = idx
    return _src_index_cache[tag]


def native_records(tag: str, source: str) -> list:
    """Every ref/5etools-src record of this tag whose own `source` equals
    `source` - the authoritative "this book defines these" work list."""
    fn, arr = TAG_TO_FILE_ARRAY[tag]
    return [r for r in load_src(fn).get(arr, []) if r.get("source") == source and "name" in r]


def resolve_record(tag: str, name: str, source) -> dict | None:
    """Look up one canonical record by (tag, name, source); if `source`
    doesn't match (or is None), fall back to a name-only match when unique."""
    idx = _src_index(tag)
    key = (name.strip().lower(), str(source or "").strip().lower())
    recs = idx.get(key)
    if recs:
        return _deref_copy(tag, recs[0])
    cands = [r for k, v in idx.items() if k[0] == name.strip().lower() for r in v]
    if len(cands) == 1:
        return _deref_copy(tag, cands[0])
    return None


def _deref_copy(tag: str, rec: dict, _depth: int = 0) -> dict:
    """Follow a `_copy` reference chain (rare for our books) to the
    fully-populated base record, shallow-merging any sibling override keys."""
    if "_copy" not in rec or _depth > 3:
        return rec
    copy_block = rec["_copy"]
    base = resolve_record(tag, copy_block.get("name", ""), copy_block.get("source"))
    if base is None:
        return rec
    merged = dict(base)
    for k, v in copy_block.items():
        if k in ("name", "source", "_mod"):
            continue
        merged[k] = v
    for k, v in rec.items():
        if k == "_copy":
            continue
        merged[k] = v
    return _deref_copy(tag, merged, _depth + 1)


# ---------------------------------------------------------------------------
# Book loading + generic tree helpers
# ---------------------------------------------------------------------------
_book_cache: dict[str, dict] = {}


def load_book(source: str) -> dict:
    if source not in _book_cache:
        _book_cache[source] = json.loads((BOOKS_DIR / f"{source}.json").read_text(encoding="utf-8"))
    return _book_cache[source]


def book_data(source: str) -> list:
    return load_book(source)["bookData"][0]["data"]


_TAG_STRIP_RE = re.compile(r"\{@(\w+)\s+([^{}|]+)(?:\|[^{}]*)?\}")
_WS_RE = re.compile(r"\s+")


def strip_tags(s) -> str:
    if not isinstance(s, str):
        return s
    return _TAG_STRIP_RE.sub(r"\2", s)


def norm(s: str) -> str:
    return _WS_RE.sub(" ", strip_tags(s)).strip().lower()


HEADING_TYPES = ("section", "entries", "inset", "insetReadaloud")

_EXCLUDED_CHAPTERS_RE = re.compile(
    r"^(equipment|spells?( lists?)?|classes|races|species|lineages|backgrounds|"
    r"feats|monsters|bestiary|creatures|magic items|treasure)\b", re.I,
)

_CROSSREF_SENTENCE_RE = re.compile(
    r"^(see (the|chapter)|for (more|a (full|complete)) (information|list)|refer to)\b", re.I,
)


def collect_book_index(data: list) -> dict:
    """One pass over a book's tree, gathering everything the evidence
    pipeline needs: headings by (lowercased) name, every statblock stub
    node, every bare list-item string, and every table cell string."""
    headings_by_name: dict = {}
    stubs: list = []
    list_items: list = []
    table_cells: list = []

    def walk(obj, path):
        if isinstance(obj, dict):
            t = obj.get("type")
            name = obj.get("name")
            if name and t in HEADING_TYPES:
                newpath = path + (name,)
                headings_by_name.setdefault(norm(name), []).append((obj, newpath))
            else:
                newpath = path
            if t == "statblock":
                stubs.append((obj.get("tag"), obj.get("name"), obj.get("source"), newpath))
            if t == "table":
                for row in obj.get("rows", []) or []:
                    for cell in row:
                        if isinstance(cell, str) and cell.strip():
                            table_cells.append((cell, newpath))
            for key in ("entries", "items"):
                for v in obj.get(key, []) or []:
                    if key == "items" and isinstance(v, str):
                        list_items.append((v, newpath))
                    walk(v, newpath)
        elif isinstance(obj, list):
            for v in obj:
                walk(v, path)

    walk(data, ())
    return {"headings": headings_by_name, "stubs": stubs, "list_items": list_items, "table_cells": table_cells}


def heading_candidates_for_name(idx: dict, name: str):
    """Real headings matching `name`, excluding top-level chapters (too
    coarse to be a single small entity) and chapters that are obviously
    about a different entity type (Equipment, Spells, Classes, ...)."""
    def _filt(cands):
        out = []
        for node, path in cands:
            if len(path) < 2:
                continue
            if path and _EXCLUDED_CHAPTERS_RE.match(path[0]):
                continue
            out.append((node, path))
        return out

    cands = _filt(idx["headings"].get(norm(name), []))
    if cands:
        return cands
    if ":" in name:
        suffix = name.split(":")[-1].strip()
        cands = _filt(idx["headings"].get(norm(suffix), []))
        if cands:
            return cands
    return []


def _strip_stub_children(entries):
    return [e for e in (entries or []) if not (isinstance(e, dict) and e.get("type") in ("statblock", "hr"))]


def content_richness(entries) -> int:
    """Rough character count of 'real' prose/table/list content, ignoring
    stub placeholders and bare cross-reference sentences ('See the X page
    for more information.')."""
    total = 0
    for e in _strip_stub_children(entries):
        if isinstance(e, str):
            if len(e) < 150 and _CROSSREF_SENTENCE_RE.match(e.strip()):
                continue
            total += len(strip_tags(e))
        elif isinstance(e, dict):
            t = e.get("type")
            if t == "table":
                total += sum(len(strip_tags(c)) for row in e.get("rows", []) for c in row if isinstance(c, str))
            elif t == "list":
                for it in e.get("items", []):
                    if isinstance(it, str):
                        total += len(strip_tags(it))
                    elif isinstance(it, dict):
                        total += content_richness(it.get("entries", [])) + len(it.get("name") or "")
            elif t in ("entries", "section", "inset", "insetReadaloud", "quote"):
                total += content_richness(e.get("entries", [])) + len(e.get("name") or "")
    return total


def has_real_content(node: dict, min_chars: int = 30) -> bool:
    return content_richness(node.get("entries", [])) >= min_chars


def resolve_entity_evidence(idx: dict, tag: str, name: str, book_source: str, allow_markdown: bool = True):
    """Find the best evidence this book has for entity (tag, name):
    1. a real heading (own prose) -> origin "markdown"
    2. a statblock stub anywhere (any source attribution) -> origin "5etools-src"
    3. the exact name as a bare list-item or table cell, but ONLY resolved
       against a record natively sourced to THIS book -> origin "5etools-src"
    Returns None if there's no textual trace at all.
    """
    if allow_markdown:
        for node, path in heading_candidates_for_name(idx, name):
            if has_real_content(node):
                return {"origin": "markdown", "node": node, "data_from": book_source, "match": "heading"}
    for (stag, sname, ssource, _spath) in idx["stubs"]:
        if stag == tag and sname and norm(sname) == norm(name):
            rec = resolve_record(tag, sname, ssource) or resolve_record(tag, name, book_source)
            if rec:
                return {"origin": "5etools-src", "record": rec, "data_from": rec.get("source", ssource), "match": "stub"}
    native = resolve_record(tag, name, book_source)
    if native and native.get("source") == book_source:
        target = norm(name)
        for (text, _p) in idx["list_items"]:
            if isinstance(text, str) and norm(text) == target:
                return {"origin": "5etools-src", "record": native, "data_from": book_source, "match": "table-mention"}
        for (text, _p) in idx["table_cells"]:
            if norm(text) == target:
                return {"origin": "5etools-src", "record": native, "data_from": book_source, "match": "table-mention"}
    return None


# ---------------------------------------------------------------------------
# Safe inline tagging, applied ONLY to markdown-origin prose (ref/5etools-src
# content already carries correct tags). Deliberately conservative: only
# closed-vocabulary / unambiguous-pattern tags, per the shared contract's
# "do not guess tags for names you cannot resolve."
# ---------------------------------------------------------------------------
_SKILLS = ["Acrobatics", "Animal Handling", "Arcana", "Athletics", "Deception", "History",
           "Insight", "Intimidation", "Investigation", "Medicine", "Nature", "Perception",
           "Performance", "Persuasion", "Religion", "Sleight of Hand", "Stealth", "Survival"]
_ABILITIES = ["Strength", "Dexterity", "Constitution", "Intelligence", "Wisdom", "Charisma"]
_CONDITIONS = ["blinded", "charmed", "deafened", "exhaustion", "frightened", "grappled",
               "incapacitated", "invisible", "paralyzed", "petrified", "poisoned", "prone",
               "restrained", "stunned", "unconscious"]
_SENSES = ["darkvision", "blindsight", "tremorsense", "truesight"]
_STANDARD_ACTIONS = ["Attack", "Cast a Spell", "Dash", "Disengage", "Dodge", "Help", "Hide",
                     "Ready", "Search", "Use an Object", "Climb onto a Bigger Creature",
                     "Disarm", "Overrun", "Shove Aside", "Tumble", "Mark", "Grapple", "Shove"]

_ALREADY_TAGGED_RE = re.compile(r"\{@[^{}]*\}")
_DICE_RE = re.compile(r"\b(\d+d\d+(?:\s*[+-]\s*\d+)?)\b")
_DC_RE = re.compile(r"\bDC\s+(\d+)\b")
_HIT_RE = re.compile(r"([+-]\s?\d+)\s+to hit\b")
_RECHARGE_RE = re.compile(r"\(Recharge (\d)(?:[-\u2013]6)?\)")
_HIT_MARKER_RE = re.compile(r"(?<=[.,]) ?Hit:\s*")
_ATK_PATTERNS = [
    (re.compile(r"\bMelee or Ranged Weapon Attack:\s*"), "{@atk mw,rw} "),
    (re.compile(r"\bMelee Weapon Attack:\s*"), "{@atk mw} "),
    (re.compile(r"\bRanged Weapon Attack:\s*"), "{@atk rw} "),
    (re.compile(r"\bMelee Spell Attack:\s*"), "{@atk ms} "),
    (re.compile(r"\bRanged Spell Attack:\s*"), "{@atk rs} "),
]
_SKILL_PAREN_RE = re.compile(r"\b(" + "|".join(_ABILITIES) + r")\s*\((" + "|".join(_SKILLS) + r")\)")
_SENSE_RE = re.compile(r"\b(" + "|".join(_SENSES) + r")\b", re.I)
_CONDITION_RE = re.compile(r"\b(" + "|".join(_CONDITIONS) + r")\b", re.I)
_ACTION_RE = re.compile(r"\bthe (" + "|".join(re.escape(a) for a in _STANDARD_ACTIONS) + r") action\b")
_STATUS_RE = re.compile(r"\b(concentration|surprised)\b", re.I)


def apply_safe_tags(text: str) -> str:
    if not isinstance(text, str) or "{@" not in text and not re.search(r"\d|DC|Hit:|concentration|surprised", text, re.I):
        pass
    mapping = {}

    def protect(m):
        key = "\x00%d\x00" % len(mapping)
        mapping[key] = m.group(0)
        return key

    s = _ALREADY_TAGGED_RE.sub(protect, text)
    for pat, tag in _ATK_PATTERNS:
        s = pat.sub(tag, s)
    s = _HIT_MARKER_RE.sub("{@h}", s)
    s = _RECHARGE_RE.sub(lambda m: "{@recharge %s}" % m.group(1), s)
    s = _HIT_RE.sub(lambda m: "{@hit %s} to hit" % m.group(1).replace(" ", ""), s)
    s = _DC_RE.sub(lambda m: "{@dc %s}" % m.group(1), s)

    def dice_repl(m):
        tail = s[m.end():m.end() + 12].lower()
        return "{@damage %s}" % m.group(1) if "damage" in tail else "{@dice %s}" % m.group(1)

    s = _DICE_RE.sub(dice_repl, s)
    s = _SKILL_PAREN_RE.sub(lambda m: "%s ({@skill %s})" % (m.group(1), m.group(2)), s)
    s = _SENSE_RE.sub(lambda m: "{@sense %s}" % m.group(0), s)
    s = _CONDITION_RE.sub(lambda m: "{@condition %s}" % m.group(0), s)
    s = _ACTION_RE.sub(lambda m: "the {@action %s} action" % m.group(1), s)
    s = _STATUS_RE.sub(lambda m: "{@status %s}" % m.group(0), s)
    for k, v in mapping.items():
        s = s.replace(k, v)
    return s


def tag_tree(obj):
    """Recursively apply apply_safe_tags to every string in an entries tree,
    returning a new structure (does not mutate the input)."""
    if isinstance(obj, str):
        return apply_safe_tags(obj)
    if isinstance(obj, list):
        return [tag_tree(v) for v in obj]
    if isinstance(obj, dict):
        return {k: (tag_tree(v) if k in ("entries", "items", "rows", "name", "caption", "by", "from") else v)
                for k, v in obj.items()}
    return obj


# ---------------------------------------------------------------------------
# Generic per-type extraction: covers action, condition, disease, status,
# object, trap, hazard, reward, variantrule, language, cult, vehicle (deity,
# table, and deck/card get dedicated pipelines further down).
#
# Work list = every ref/5etools-src record natively sourced to this book
# (that is the authoritative "this book defines these" list). For each:
#   - a real Markdown heading -> use our own prose (+ the native record's
#     other structured fields), origin "markdown"
#   - otherwise a stub/mention in THIS book -> origin "5etools-src", the
#     native record, match "stub"/"table-mention"
#   - otherwise (chapter only names it via a pointer sentence, e.g. "see the
#     Traps page") -> still import the native record wholesale, origin
#     "5etools-src", match "source-complete" (policy: every native record a
#     book owns gets extracted one way or another)
# PLUS: cross-book reprints - a stub in this book pointing at a DIFFERENT
# source's record (e.g. a Dungeon Master's Screen insert reprinting a PHB
# condition) still gets extracted under this book's source, data pulled
# from the stub's actual source.
# ---------------------------------------------------------------------------

def _finalize_required(tag: str, entity: dict) -> dict:
    if tag == "action" and "page" not in entity:
        entity["page"] = 0
    return entity


def extract_generic_type(tag: str, source: str, idx: dict, allow_markdown: bool = True, claimed_ids: set | None = None):
    entities = []
    provenance = {}
    counts = Counter()
    seen = set()

    # Pass 1: cross-book reprints via stub (book has its own entry/stub for
    # an entity natively defined by a DIFFERENT source).
    for (stag, sname, ssource, _path) in idx["stubs"]:
        if stag != tag or not sname:
            continue
        key = norm(sname)
        if key in seen:
            continue
        native_here = resolve_record(tag, sname, source)
        if native_here and native_here.get("source") == source:
            continue  # handled with (possibly better) evidence in pass 2
        rec = resolve_record(tag, sname, ssource)
        if not rec:
            continue
        entity = filter_record(tag, rec, sname, source)
        entity = _finalize_required(tag, entity)
        entities.append(entity)
        provenance[sname] = {"origin": "5etools-src", "data_from": rec.get("source", ssource), "match": "stub"}
        counts["5etools-src:stub(cross-book)"] += 1
        seen.add(key)

    # Pass 2: every record this book natively owns.
    for rec0 in native_records(tag, source):
        name = rec0["name"]
        key = norm(name)
        if key in seen:
            continue
        seen.add(key)
        md_allowed = allow_markdown and tag not in STATS_DOMINANT_TAGS
        ev = None
        if md_allowed:
            for node, _path in heading_candidates_for_name(idx, name):
                if has_real_content(node):
                    ev = {"origin": "markdown", "node": node}
                    break
        if ev is None:
            for (stag, sname, ssource, _path) in idx["stubs"]:
                if stag == tag and sname and norm(sname) == key:
                    ev = {"origin": "5etools-src", "match": "stub", "data_from": ssource}
                    break
        if ev is None:
            target = key
            for (text, _p) in idx["list_items"]:
                if isinstance(text, str) and norm(text) == target:
                    ev = {"origin": "5etools-src", "match": "table-mention", "data_from": source}
                    break
        if ev is None:
            for (text, _p) in idx["table_cells"]:
                if norm(text) == key:
                    ev = {"origin": "5etools-src", "match": "table-mention", "data_from": source}
                    break

        if ev and ev["origin"] == "markdown":
            entity = filter_record(tag, rec0, name, source)
            entity["entries"] = tag_tree(ev["node"].get("entries", []))
            if claimed_ids is not None:
                mark_claimed(ev["node"], claimed_ids)
            match = "heading"
        elif ev:
            entity = filter_record(tag, rec0, name, source)
            match = ev["match"]
        else:
            entity = filter_record(tag, rec0, name, source)
            match = "source-complete"
        entity = _finalize_required(tag, entity)
        entities.append(entity)
        origin = "markdown" if ev and ev["origin"] == "markdown" else "5etools-src"
        provenance[name] = {"origin": origin, "data_from": source if origin == "markdown" else rec0.get("source", source), "match": match}
        counts[f"{origin}:{match}"] += 1

    return entities, provenance, counts


# ---------------------------------------------------------------------------
# Deity: dedicated pipeline. Most books present deities as a reference TABLE
# (colLabels like Deity/Alignment/[Province/]Suggested Domains/Symbol) - a
# cell like "{@b Auril}, goddess of winter" gives name+title directly, and
# the other columns give alignment/province/domains/symbol structurally, no
# regex-over-prose needed. Some books (SCAG, MTF) ALSO have a real per-deity
# lore heading for some/all table rows - when present we use it for
# `entries`. Native deity records with neither a table row nor a heading
# fall through to the generic pipeline (stub / source-complete).
# ---------------------------------------------------------------------------
_DEITY_NAME_COL_RE = re.compile(r"^(deity|god|gods|name)$", re.I)
_DEITY_ALIGN_COL_RE = re.compile(r"^align", re.I)
_DEITY_PROVINCE_COL_RE = re.compile(r"^province", re.I)
_DEITY_DOMAIN_COL_RE = re.compile(r"domain", re.I)
_DEITY_SYMBOL_COL_RE = re.compile(r"symbol", re.I)
_DEITY_CELL_NAME_RE = re.compile(r"^\{@b\s+([^}|]+)\}\s*,?\s*(.*)$")

_PANTHEON_OF_RE = re.compile(r"^(?:deities|gods) of (?:the )?(.+)$", re.I)
_X_PANTHEON_RE = re.compile(r"^(?:the )?(.+?) pantheon$", re.I)
_PANTHEON_OF_X_RE = re.compile(r"^pantheon of (.+)$", re.I)
_X_DEITIES_RE = re.compile(r"^(.+?) (?:deities|gods)(?: \(.*\))?$", re.I)
_PAREN_RE = re.compile(r"\(([^()]+)\)\s*$")


def _looks_like_deity_table(col_labels) -> bool:
    if not col_labels:
        return False
    hits = 0
    for lbl in col_labels:
        l = strip_tags(lbl).strip()
        if _DEITY_NAME_COL_RE.match(l) or _DEITY_ALIGN_COL_RE.match(l) or _DEITY_PROVINCE_COL_RE.match(l) \
                or _DEITY_DOMAIN_COL_RE.search(l) or _DEITY_SYMBOL_COL_RE.search(l):
            hits += 1
    return hits >= 2


def _split_alignment(raw: str):
    raw = raw.strip().upper()
    if not raw or raw in ("-", "\u2014", "VARIES", "ANY"):
        return None
    chars = [c for c in raw if c in ALIGNMENT_CHARS]
    return chars or None


def _derive_pantheon_from_path(path):
    for h in reversed(path[:-1]):
        h = strip_tags(h).strip()
        m = _PANTHEON_OF_RE.match(h) or _PANTHEON_OF_X_RE.match(h)
        if m:
            return m.group(1).strip()
        m = _X_PANTHEON_RE.match(h)
        if m:
            return m.group(1).strip()
        m = _X_DEITIES_RE.match(h)
        if m:
            return m.group(1).strip()
    return None


def _parse_deity_table(table_node, path):
    labels = table_node.get("colLabels") or []
    name_col = 0
    align_col = province_col = domains_col = symbol_col = None
    category = None
    for i, lbl in enumerate(labels):
        l = strip_tags(lbl).strip()
        if _DEITY_NAME_COL_RE.match(l):
            name_col = i
        elif _DEITY_ALIGN_COL_RE.match(l):
            align_col = i
        elif _DEITY_PROVINCE_COL_RE.match(l):
            province_col = i
        elif _DEITY_DOMAIN_COL_RE.search(l):
            domains_col = i
        elif _DEITY_SYMBOL_COL_RE.search(l):
            symbol_col = i
        elif i == 0:
            category = l
    pantheon_hint = _derive_pantheon_from_path(path)
    rows_out = []
    for row in table_node.get("rows", []):
        if name_col >= len(row) or not isinstance(row[name_col], str):
            continue
        cell = row[name_col].strip()
        m = _DEITY_CELL_NAME_RE.match(cell)
        if m:
            name, rest = m.group(1).strip(), m.group(2).strip()
        else:
            parts = strip_tags(cell).split(",", 1)
            name = parts[0].strip()
            rest = parts[1].strip() if len(parts) > 1 else ""
        if not name:
            continue
        rec = {"name": name, "pantheon_hint": pantheon_hint}
        if rest:
            rec["title"] = rest
        if align_col is not None and align_col < len(row) and isinstance(row[align_col], str):
            align = _split_alignment(row[align_col])
            if align:
                rec["alignment"] = align
        if province_col is not None and province_col < len(row) and isinstance(row[province_col], str):
            prov = strip_tags(row[province_col]).strip()
            if prov:
                rec["province"] = prov
        if domains_col is not None and domains_col < len(row) and isinstance(row[domains_col], str):
            doms = [d.strip() for d in strip_tags(row[domains_col]).split(",") if d.strip()]
            if doms:
                rec["domains"] = doms
        if symbol_col is not None and symbol_col < len(row) and isinstance(row[symbol_col], str):
            sym = strip_tags(row[symbol_col]).strip()
            if sym:
                rec["symbol"] = sym
        if category:
            rec["category"] = category
        rows_out.append(rec)
    return rows_out


def _find_deity_tables(data):
    found = []

    def walk(obj, path):
        if isinstance(obj, dict):
            name = obj.get("name")
            newpath = path + (name,) if name and obj.get("type") in HEADING_TYPES else path
            if obj.get("type") == "table" and _looks_like_deity_table(obj.get("colLabels")):
                found.append((obj, newpath))
            for key in ("entries", "items"):
                for v in obj.get(key, []) or []:
                    walk(v, newpath)
        elif isinstance(obj, list):
            for v in obj:
                walk(v, path)

    walk(data, ())
    return found


def extract_deities(source: str, data: list, idx: dict, claimed_ids: set | None = None):
    entities = []
    provenance = {}
    counts = Counter()
    seen = set()

    table_rows: dict = {}
    for table_node, path in _find_deity_tables(data):
        if claimed_ids is not None:
            mark_claimed(table_node, claimed_ids)
        for row in _parse_deity_table(table_node, path):
            table_rows.setdefault(norm(row["name"]), row)

    for rec0 in native_records("deity", source):
        name = rec0["name"]
        key = norm(name)
        if key in seen:
            continue
        seen.add(key)
        entity = filter_record("deity", rec0, name, source)
        origin = "5etools-src"
        match = "source-complete"

        row = table_rows.get(key)
        if row is not None:
            origin = "markdown"
            match = "table"
            if row.get("title"):
                entity["title"] = row["title"]
            elif "title" in entity:
                pass
            if row.get("alignment"):
                entity["alignment"] = row["alignment"]
            if row.get("province"):
                entity["province"] = row["province"]
            if row.get("domains"):
                entity["domains"] = row["domains"]
            if row.get("symbol"):
                entity["symbol"] = row["symbol"]
            if row.get("category") and not entity.get("category"):
                entity["category"] = row["category"]
            if row.get("pantheon_hint") and not rec0.get("pantheon"):
                entity["pantheon"] = row["pantheon_hint"]

        heading_hit = None
        for node, _path in heading_candidates_for_name(idx, name):
            if has_real_content(node):
                heading_hit = node
                break
        if heading_hit is not None:
            origin = "markdown"
            match = "table+heading" if row is not None else "heading"
            entity["entries"] = tag_tree(heading_hit.get("entries", []))
            if claimed_ids is not None:
                mark_claimed(heading_hit, claimed_ids)

        if "pantheon" not in entity or not entity["pantheon"]:
            entity["pantheon"] = rec0.get("pantheon") or "Unknown"

        entities.append(entity)
        provenance[name] = {"origin": origin, "data_from": source if origin == "markdown" else rec0.get("source", source), "match": match}
        counts[f"{origin}:{match}"] += 1

    # Cross-book deity reprints via stub (a book's own entry points at a
    # deity natively defined elsewhere, e.g. a sourcebook mentioning a
    # Forgotten Realms god with a full PHB-sourced write-up).
    for (stag, sname, ssource, _path) in idx["stubs"]:
        if stag != "deity" or not sname:
            continue
        key = norm(sname)
        if key in seen:
            continue
        native_here = resolve_record("deity", sname, source)
        if native_here and native_here.get("source") == source:
            continue
        rec = resolve_record("deity", sname, ssource)
        if not rec:
            continue
        entity = filter_record("deity", rec, sname, source)
        entities.append(entity)
        provenance[sname] = {"origin": "5etools-src", "data_from": rec.get("source", ssource), "match": "stub"}
        counts["5etools-src:stub(cross-book)"] += 1
        seen.add(key)

    # Pure-Markdown deities: a table row this book's own text presents as a
    # deity (name/alignment/domains/symbol), with no corresponding record in
    # ref/5etools-src at all - built entirely from our own content.
    for key, row in table_rows.items():
        if key in seen:
            continue
        seen.add(key)
        name = row["name"]
        entity = {"name": name, "source": source}
        if row.get("title"):
            entity["title"] = row["title"]
        if row.get("alignment"):
            entity["alignment"] = row["alignment"]
        if row.get("province"):
            entity["province"] = row["province"]
        if row.get("domains"):
            entity["domains"] = row["domains"]
        if row.get("symbol"):
            entity["symbol"] = row["symbol"]
        if row.get("category"):
            entity["category"] = row["category"]
        entity["pantheon"] = row.get("pantheon_hint") or "Unknown"

        match = "table"
        for node, _path in heading_candidates_for_name(idx, name):
            if has_real_content(node):
                entity["entries"] = tag_tree(node.get("entries", []))
                match = "table+heading"
                if claimed_ids is not None:
                    mark_claimed(node, claimed_ids)
                break

        entities.append(entity)
        provenance[name] = {"origin": "markdown", "data_from": source, "match": match}
        counts[f"markdown:{match}(no-native-record)"] += 1

    return entities, provenance, counts


# ---------------------------------------------------------------------------
# Table (standalone): wave 1 already collapses "a heading whose ENTIRE
# content is one table" into a bare `{type:"table", "caption": <heading
# name>, "id": <heading id>, ...}` node - that collapse is precisely the
# signal for "this table stands on its own as reference material", as
# opposed to a table embedded alongside prose inside some other entity's
# write-up (which keeps no caption/id of its own). We extract every such
# captioned table that isn't already part of a subtree we claimed for a
# different entity type (tracked via `claimed_ids`), excluding the
# class/background/feature "level progression" table shape (first column a
# plain ordinal like "1st-4th"/"Rank", not a die range).
# ---------------------------------------------------------------------------
_PROGRESSION_COL_RE = re.compile(r"\b(level|rank|tier)\b", re.I)
_DIE_COL_RE = re.compile(r"\bd\d+\b", re.I)


def mark_claimed(node, claimed_ids: set):
    if isinstance(node, dict):
        nid = node.get("id")
        if nid:
            claimed_ids.add(nid)
        for key in ("entries", "items"):
            for v in node.get(key, []) or []:
                mark_claimed(v, claimed_ids)
        for row in node.get("rows", []) or []:
            for c in row:
                mark_claimed(c, claimed_ids)
    elif isinstance(node, list):
        for v in node:
            mark_claimed(v, claimed_ids)


def _is_progression_table(table_node) -> bool:
    labels = table_node.get("colLabels") or []
    if not labels:
        return False
    first = strip_tags(labels[0]).strip()
    return bool(_PROGRESSION_COL_RE.search(first) and not _DIE_COL_RE.search(first))


def extract_standalone_tables(source: str, data: list, claimed_ids: set):
    entities = []
    provenance = {}
    counts = Counter()
    seen_names = set()
    native = {norm(r["name"]): r for r in native_records("table", source)}

    def walk(obj, path):
        if isinstance(obj, dict):
            name = obj.get("name")
            newpath = path + (name,) if name and obj.get("type") in HEADING_TYPES else path
            if obj.get("type") == "table" and "caption" in obj and obj.get("id") not in claimed_ids:
                if not _is_progression_table(obj):
                    cap = obj["caption"]
                    key = norm(cap)
                    n = 1
                    uniq = cap
                    while norm(uniq) in seen_names:
                        n += 1
                        uniq = f"{cap} ({n})"
                    seen_names.add(norm(uniq))
                    entity = {
                        "name": uniq,
                        "source": source,
                        "rows": tag_tree(obj.get("rows", [])),
                    }
                    for k in ("colLabels", "colLabelRows", "colStyles", "rowLabels", "rowStyles",
                              "footnotes", "intro", "outro", "isStriped", "isNameGenerator", "style"):
                        if k in obj:
                            entity[k] = tag_tree(obj[k]) if k in ("colLabels", "footnotes", "intro", "outro") else obj[k]
                    entities.append(entity)
                    origin = "markdown"
                    match = "heading"
                    nat = native.get(key)
                    if nat is not None:
                        match = "heading+native-confirmed"
                    provenance[uniq] = {"origin": origin, "data_from": source, "match": match, "section_id": obj.get("id")}
                    counts[f"{origin}:{match}"] += 1
            for k in ("entries", "items"):
                for v in obj.get(k, []) or []:
                    walk(v, newpath)
            for row in obj.get("rows", []) or []:
                for c in row:
                    walk(c, newpath)
        elif isinstance(obj, list):
            for v in obj:
                walk(v, path)

    walk(data, ())

    # Native table records this book owns that never appeared as a
    # standalone captioned node at all (e.g. only mentioned via a stub).
    for name_key, rec0 in native.items():
        if name_key in seen_names:
            continue
        name = rec0["name"]
        entity = filter_record("table", rec0, name, source)
        entities.append(entity)
        provenance[name] = {"origin": "5etools-src", "data_from": source, "match": "source-complete"}
        counts["5etools-src:source-complete"] += 1
        seen_names.add(name_key)

    return entities, provenance, counts


# ---------------------------------------------------------------------------
# Deck / Card: a `deck` is mostly metadata (a `cards` array of
# "Name|Set|Source" references) - once a deck's presence in this book is
# confirmed (heading/stub/mention, or it's simply native and gets the same
# source-complete treatment as everything else), every card it enumerates is
# treated as confirmed too (you can't meaningfully have "Condition Cards"
# without its 15 specific cards - they aren't independently-discoverable
# content). Cards not covered by any deck membership are still individually
# resolved against their own heading/stub/mention/source-complete evidence.
# ---------------------------------------------------------------------------

def _deck_card_uids(rec: dict):
    out = []
    for c in rec.get("cards", []) or []:
        uid = c.get("uid") if isinstance(c, dict) else c
        if uid:
            out.append(uid)
    return out


def extract_decks_and_cards(source: str, idx: dict, claimed_ids: set | None = None):
    deck_entities = []
    card_entities = []
    deck_prov = {}
    card_prov = {}
    counts = Counter()
    confirmed = {}  # (name_norm, source_norm) -> set_name (for provenance context)
    card_force_src = source in CARD_FORCE_SRC_BOOKS

    def _evidence_match(tag, name):
        for node, _path in heading_candidates_for_name(idx, name):
            if has_real_content(node):
                return ("markdown", node)
        for (stag, sname, ssource, _p) in idx["stubs"]:
            if sname and norm(sname) == norm(name) and (stag == tag or (tag == "deck" and stag == "item")):
                return ("5etools-src", "stub")
        key = norm(name)
        for (text, _p) in idx["list_items"]:
            if norm(text) == key:
                return ("5etools-src", "table-mention")
        for (text, _p) in idx["table_cells"]:
            if norm(text) == key:
                return ("5etools-src", "table-mention")
        return (None, None)

    for rec0 in native_records("deck", source):
        name = rec0["name"]
        kind, detail = (None, None) if card_force_src else _evidence_match("deck", name)
        match = detail if kind == "5etools-src" else ("heading" if kind == "markdown" else "source-complete")
        entity = filter_record("deck", rec0, name, source)
        deck_entities.append(entity)
        deck_prov[name] = {"origin": "5etools-src", "data_from": source, "match": match}
        counts[f"deck:5etools-src:{match}"] += 1
        for uid in _deck_card_uids(rec0):
            parts = uid.split("|")
            cname = parts[0]
            csource = parts[-1] if len(parts) > 1 else source
            confirmed[(norm(cname), norm(csource))] = rec0.get("name")

    # Cross-book deck reprints via stub.
    for (stag, sname, ssource, _path) in idx["stubs"]:
        if stag not in ("deck",) or not sname:
            continue
        native_here = resolve_record("deck", sname, source)
        if native_here and native_here.get("source") == source:
            continue
        if sname in deck_prov:
            continue
        rec = resolve_record("deck", sname, ssource)
        if not rec:
            continue
        entity = filter_record("deck", rec, sname, source)
        deck_entities.append(entity)
        deck_prov[sname] = {"origin": "5etools-src", "data_from": rec.get("source", ssource), "match": "stub"}
        counts["deck:5etools-src:stub(cross-book)"] += 1
        for uid in _deck_card_uids(rec):
            parts = uid.split("|")
            cname = parts[0]
            csource = parts[-1] if len(parts) > 1 else rec.get("source", ssource)
            confirmed[(norm(cname), norm(csource))] = rec.get("name")

    seen_cards = set()

    def _build_card(rec0, name, origin_kind, detail):
        entity = filter_record("card", rec0, name, source)
        match = "source-complete"
        if origin_kind == "markdown":
            entity["entries"] = tag_tree(detail.get("entries", []))
            if claimed_ids is not None:
                mark_claimed(detail, claimed_ids)
            match = "heading"
            origin = "markdown"
        elif origin_kind == "5etools-src":
            match = detail
            origin = "5etools-src"
        else:
            origin = "5etools-src"
        card_entities.append(entity)
        card_prov[name if name not in card_prov else f"{name}|{rec0.get('set')}"] = {
            "origin": origin, "data_from": source if origin == "markdown" else rec0.get("source", source), "match": match,
        }
        counts[f"card:{origin}:{match}"] += 1

    # Cards independently resolvable in THIS book (native or reprinted).
    for rec0 in native_records("card", source):
        dedup_key = (norm(rec0["name"]), norm(source), norm(rec0.get("set") or ""))
        if dedup_key in seen_cards:
            continue
        seen_cards.add(dedup_key)
        name = rec0["name"]
        if card_force_src:
            kind, detail = (None, None)
        else:
            kind, detail = _evidence_match("card", name)
        if kind is None and (norm(name), norm(source)) in confirmed:
            kind, detail = (None, None)  # confirmed via deck membership below; still source-complete-equivalent
        _build_card(rec0, name, kind, detail)

    # Cards confirmed only via deck membership (not independently native-
    # resolvable by name+THIS source above because resolve_record needed an
    # exact (name, source) match that native_records already covers - this
    # loop instead sweeps every (name, source) a confirmed deck enumerated,
    # in case the card's own canonical `source` differs subtly or it wasn't
    # caught above for any reason).
    for (cname_norm, csource_norm), _deckname in confirmed.items():
        dedup_probe = [k for k in seen_cards if k[0] == cname_norm]
        if dedup_probe:
            continue
        rec0 = resolve_record("card", cname_norm, None)
        if not rec0:
            continue
        dedup_key = (norm(rec0["name"]), norm(source), norm(rec0.get("set") or ""))
        if dedup_key in seen_cards:
            continue
        seen_cards.add(dedup_key)
        _build_card(rec0, rec0["name"], None, None)

    return deck_entities, card_entities, deck_prov, card_prov, counts


# ---------------------------------------------------------------------------
# Per-book orchestration
# ---------------------------------------------------------------------------
GENERIC_TAGS = [
    "action", "condition", "disease", "status", "object", "trap", "hazard",
    "reward", "variantrule", "language", "cult", "vehicle", "psionic",
]


def load_sources():
    doc = json.loads(SOURCES_JSON.read_text(encoding="utf-8"))
    return doc["books"]


def process_book(source: str):
    data = book_data(source)
    idx = collect_book_index(data)
    claimed_ids: set = set()

    shard: dict = {}
    provenance: dict = {}
    counts_total = Counter()

    for tag in GENERIC_TAGS:
        entities, prov, counts = extract_generic_type(tag, source, idx, claimed_ids=claimed_ids)
        if entities:
            shard[tag] = entities
            provenance[tag] = prov
        counts_total.update(counts)

    deity_entities, deity_prov, deity_counts = extract_deities(source, data, idx, claimed_ids=claimed_ids)
    if deity_entities:
        shard["deity"] = deity_entities
        provenance["deity"] = deity_prov
    counts_total.update({f"deity:{k}": v for k, v in deity_counts.items()})

    deck_entities, card_entities, deck_prov, card_prov, dc_counts = extract_decks_and_cards(source, idx, claimed_ids=claimed_ids)
    if deck_entities:
        shard["deck"] = deck_entities
        provenance["deck"] = deck_prov
    if card_entities:
        shard["card"] = card_entities
        provenance["card"] = card_prov
    counts_total.update(dc_counts)

    # Standalone tables run LAST so claimed_ids reflects every other entity
    # type's markdown-sourced subtree.
    table_entities, table_prov, table_counts = extract_standalone_tables(source, data, claimed_ids)
    if table_entities:
        shard["table"] = table_entities
        provenance["table"] = table_prov
    counts_total.update({f"table:{k}": v for k, v in table_counts.items()})

    if not shard:
        return None, None, counts_total

    book_json = load_book(source)
    meta = {
        "sources": book_json["_meta"]["sources"],
        "dateAdded": GEN_TIME,
        "dateLastModified": GEN_TIME,
        "edition": book_json["_meta"].get("edition", "classic"),
    }
    shard_out = {"_meta": meta, **shard}
    return shard_out, provenance, counts_total


# ---------------------------------------------------------------------------
# Lightweight sanity net: cross-check wave-1's rough category guesses
# (sections.jsonl) against what we actually extracted, to surface any
# official-adventure-book content that might not be in ref/5etools-src at
# all (so never reached via native_records()).
# ---------------------------------------------------------------------------
SECTIONS_JSONL = REPO_ROOT / "ref" / "5etools" / "sections.jsonl"
GUESS_CATEGORY_FOR_TAG = {
    "deity": "deity", "trap": "trap-hazard", "hazard": "trap-hazard",
    "condition": "condition-disease", "disease": "condition-disease",
    "reward": "reward", "vehicle": "vehicle", "object": "object",
}


def unmatched_section_guesses(source: str, extracted_names_by_tag: dict):
    if not SECTIONS_JSONL.exists():
        return []
    wanted_cats = set(GUESS_CATEGORY_FOR_TAG.values())
    extracted_norms = {norm(n) for names in extracted_names_by_tag.values() for n in names}
    out = []
    with SECTIONS_JSONL.open(encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            if row.get("source") != source or row.get("category") not in wanted_cats:
                continue
            guesses = row.get("entities_guess") or [row["heading"]]
            if all(norm(g) not in extracted_norms for g in guesses):
                out.append((row["category"], row["heading"], row["id"]))
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sources = load_sources()

    grand_counts = Counter()
    per_book_type_counts: dict[str, Counter] = {}
    books_written = 0
    entities_written = 0
    sanity_flags: dict[str, list] = {}
    errors: list = []

    for meta in sources:
        source = meta["source"]
        try:
            shard, provenance, counts = process_book(source)
        except Exception as exc:  # noqa: BLE001
            errors.append((source, f"{type(exc).__name__}: {exc}"))
            print(f"ERROR processing {source}: {exc}", file=sys.stderr)
            continue
        grand_counts.update(counts)
        if shard is None:
            continue
        books_written += 1
        type_counts = Counter()
        names_by_tag = {}
        for tag, items in shard.items():
            if tag == "_meta":
                continue
            type_counts[tag] = len(items)
            names_by_tag[tag] = [it["name"] for it in items]
        entities_written += sum(type_counts.values())
        per_book_type_counts[source] = type_counts

        out_path = OUT_DIR / f"{source}.json"
        out_path.write_text(json.dumps(shard, indent="\t", ensure_ascii=False) + "\n", encoding="utf-8")
        prov_path = OUT_DIR / f"{source}.provenance.json"
        prov_path.write_text(json.dumps(provenance, indent="\t", ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")

        flags = unmatched_section_guesses(source, names_by_tag)
        if flags:
            sanity_flags[source] = flags

    print(f"Wrote {books_written} shard files, {entities_written} entities total, from {len(sources)} books.\n")

    print("Per-book entity counts (non-empty books only):")
    for source, type_counts in per_book_type_counts.items():
        line = ", ".join(f"{t}={n}" for t, n in sorted(type_counts.items()))
        print(f"  {source:20} {line}")

    print("\nOrigin/match breakdown per type (aggregated across all 51 books):")
    by_type: dict[str, Counter] = defaultdict(Counter)
    for key, n in grand_counts.items():
        parts = key.split(":")
        t = parts[0]
        rest = ":".join(parts[1:])
        by_type[t][rest] += n
    for t in sorted(by_type):
        print(f"  {t}:")
        for rest, n in by_type[t].most_common():
            print(f"    {rest:30} {n}")

    if sanity_flags:
        total_flagged = sum(len(v) for v in sanity_flags.values())
        print(f"\nSanity net: {total_flagged} wave-1 category-guessed section(s) across "
              f"{len(sanity_flags)} book(s) have NO matching extracted entity name "
              f"(may be lore mentions, may be real gaps - spot-check):")
        for source, flags in sanity_flags.items():
            for cat, heading, sid in flags[:30]:
                print(f"  {source:14} [{cat:18}] {heading}  ({sid})")

    if errors:
        print(f"\nERRORS ({len(errors)}):")
        for source, e in errors:
            print(f"  - {source}: {e}")

    print(f"\nBooks with zero world-shard entities: "
          f"{len(sources) - books_written - len(errors)}")


if __name__ == "__main__":
    main()
