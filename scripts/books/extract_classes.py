#!/usr/bin/env python3
"""Extract `class` / `subclass` / `classFeature` / `subclassFeature` entities
for all 51 books into ref/5etools/shards/classes/<SOURCE>.json.

WHY THIS SCRIPT DOES NOT PARSE PROSE OUT OF ref/books/*.md FOR THIS TYPE
-------------------------------------------------------------------------
ref/books/*.md was captured from the 5etools site's "book reader" pages. For
every official book, the 5etools site already has `class`/`subclass` as
*structured, interactive* data (class tables, level-gated feature lists), so
the book reader never flows that content as prose. Instead it emits a dead
placeholder for each class/subclass page, literally:

    <td ... data-rd-tag="class" data-rd-uid="Barbarian|PHB" data-rd-source="PHB"
        data-rd-hash="barbarian_phb" ...>
        <i>Loading "<a href="classes.html#barbarian_phb" data-vet-page="classes.html"
            data-vet-source="PHB" data-vet-hash="barbarian_phb" ...>Barbarian</a>"...</i>
    </td>

This is true for *every* class/subclass mention in *every* one of the 51
books (verified: `data-rd-tag="class"`/`data-rd-tag="subclass"` appear 69
times total across all 51 books, and in every single case the actual rules
text is absent; classFeature/subclassFeature are never individually
stubbed, only ever pulled in as part of a class/subclass bundle). A further
handful of books name an individual feature, or a whole subclass, in plain
un-stubbed text instead -- a bare line ("Primal Knowledge (*3rd-level
barbarian feature*)" in TCE), a heading ("### Maneuver Options", TCE), a
lore table (SCAG's Uthgardt totem table naming "Elk"/"Tiger"), a "new
subclass options" summary table that also names the class per row (XGE), or
plain prose naming the class right next to the subclass ("a cleric chooses
a Divine Domain. This source adds the Order Domain...", GGR) -- in every
case without the detailed rules prose surviving capture either.

So the only way to recover this entity family at all is the policy agreed
with Main for wave 2: when the Markdown has a stub/bare-name/table-mention
for an entity that is genuinely *this book's own* content, fill it from the
official 5etools reference data mirrored locally (read-only, no network) at
`ref/5etools-src/data/class/*.json`. This script implements exactly that,
as a sequence of passes of decreasing textual evidence:

  PASS 1   "stub"           resolve every data-rd-tag="class"/"subclass"
                             placeholder via its data-rd-uid, and pull the
                             whole linked bundle (a class's own
                             classFeatures, or a subclass's own
                             subclassFeatures).
  PASS 2   "table-mention"  resolve bare "Name (*Nth-level X feature*)"
                             lines (TCE's "Optional Class Features"
                             sections) against classFeature/subclassFeature
                             records whose own `source` is this book.
  PASS 2.5 "table-mention"  whole subclasses named (no stub at all) in this
                             book's own prose/headings/tables, evidenced by
                             the class appearing alongside (DMG, EGW, XGE).
  PASS 2.5b "table-mention" as 2.5, but for a subclass canonically filed
                             under a *different* book upstream (otherSources
                             links it to this one) -- e.g. GGR's "Order
                             Domain" and "Circle of Spores" are filed under
                             TCE upstream, but GGR's own prose genuinely
                             introduces them, so they're pulled from TCE's
                             data and re-homed under GGR.
  PASS 3   "table-mention"  individual orphan classFeature/subclassFeature
                             mentions not covered by 2/2.5 (e.g. SCAG's
                             Totem Warrior "Elk"/"Tiger" additions).
  PASS 4   "source-complete" final completeness net: any remaining record
                             whose own `source` is this book, regardless of
                             whether the Markdown shows any trace of it at
                             all (verified to add exactly two: TCE's "Deft
                             Explorer Improvement" at levels 6 and 10, which
                             has no textual trace anywhere in TCE's prose).

Per Main's clarification: if *this* book has its own stub/heading/mention for
an entity, it is extracted under *this* book's source even when the canonical
data's `source` is a different book (e.g. ERLW's own "Artificer" placeholder
resolves via TCE's data, since 5etools' live data consolidates the class
under its TCE reprint and only cross-references ERLW). In that case every
source-like field (`source`/`classSource`/`subclassSource`) that equalled the
*original* canonical source is rewritten to this book's code (so the shard is
internally self-consistent), and the original source is recorded as
`data_from` in the provenance sidecar.

Output per book with any matches:
  ref/5etools/shards/classes/<SOURCE>.json              (the shard)
  ref/5etools/shards/classes/<SOURCE>.provenance.json    (per-entity origin)
Plus a combined ref/5etools/shards/classes/_extraction_report.json.

Python 3.9 stdlib only.
"""
from __future__ import annotations

import copy
import json
import re
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BOOKS_MD_DIR = REPO_ROOT / "ref/books"
BOOKS_JSON_DIR = REPO_ROOT / "ref/5etools/books"
SOURCES_JSON = REPO_ROOT / "ref/5etools/sources.json"
CLASS_SRC_DIR = REPO_ROOT / "ref/5etools-src/data/class"
SCHEMA_PATH = (
    REPO_ROOT
    / "ref/5etools/tooling/node_modules/5etools-utils/schema/brew/class/class.json"
)
OUT_DIR = REPO_ROOT / "ref/5etools/shards/classes"

sys.path.insert(0, str(REPO_ROOT / "scripts/books"))
from structure_books import slugify  # noqa: E402  (reuse wave-1's exact slug convention)

# --------------------------------------------------------------------------
# Regexes
# --------------------------------------------------------------------------
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
TD_RE = re.compile(r"<td([^>]*)>")
TAG_RE = re.compile(r'data-rd-tag="(class|subclass)"')
UID_RE = re.compile(r'data-rd-uid="([^"]*)"')
LEADING_TAG_RE = re.compile(r"^(?:</?[a-zA-Z][^>]*>)+")
MINITOC_RE = re.compile(
    r"^(.+?)\s*\(\*(\d+)(?:st|nd|rd|th)-level\s+([A-Za-z][A-Za-z' ]*?)\s+feature"
    r"(?:,\s*which replaces[^*]*)?\*\)\s*$"
)

# Fields that are schema-legal but we deliberately never emit: page numbers
# (no page info in our corpus), reprint/other-source bookkeeping that becomes
# misleading once an entity is re-homed under a different book, Foundry VTT
# metadata (no Foundry pipeline here), and per-entity edition (the file-level
# `_meta.edition` already covers it).
DENYLIST = {
    "page",
    "otherSources",
    "reprintedAs",
    "isReprinted",
    "referenceSources",
    "hasFluff",
    "hasFluffImages",
    "fluff",
    "foundrySystem",
    "foundryFlags",
    "foundryImg",
    "foundryAdvancement",
    "foundryAdvice",
    "edition",
    "alias",
}


def schema_allowlists() -> dict:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    defs = schema["$defs"]

    def props(name: str) -> set:
        d = defs[name]
        if "anyOf" in d:
            d = d["anyOf"][0]  # branch 0 is always the full-data shape, not `_copy`
        return set(d["properties"].keys()) - DENYLIST

    return {k: props(k) for k in ("class", "subclass", "classFeature", "subclassFeature")}


def filter_props(obj: dict, allowed: set) -> dict:
    return {k: v for k, v in obj.items() if k in allowed}


# --------------------------------------------------------------------------
# Reference data (ref/5etools-src/data/class/*.json)
# --------------------------------------------------------------------------
def load_reference() -> dict:
    data = {"class": [], "subclass": [], "classFeature": [], "subclassFeature": []}
    for f in sorted(CLASS_SRC_DIR.glob("class-*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        for k in data:
            data[k].extend(d.get(k, []))
    return data


def build_indices(ref: dict) -> dict:
    idx: dict = {}

    classes = {}
    for c in ref["class"]:
        if "_copy" in c:
            continue  # derived overlay (2024-rules variant etc.), not full data
        classes[(c["name"], c["source"])] = c
    idx["classes"] = classes

    cf_by_class: dict = {}
    cf_by_lvl_name_src: dict = {}
    for cf in ref["classFeature"]:
        if "_copy" in cf:
            continue
        cs = cf.get("classSource") or "PHB"
        cf_by_class.setdefault((cf["className"], cs), []).append(cf)
        cf_by_lvl_name_src.setdefault((cf["level"], cf["name"], cf["source"]), []).append(
            (cf["className"], cs, cf)
        )
    idx["cf_by_class"] = cf_by_class
    idx["cf_by_lvl_name_src"] = cf_by_lvl_name_src

    subclasses = {}
    for sc in ref["subclass"]:
        if "_copy" in sc or "subclassFeatures" not in sc:
            continue
        cs = sc.get("classSource") or "PHB"
        subclasses[(sc["className"], cs, sc["shortName"], sc["source"])] = sc
    idx["subclasses"] = subclasses

    sf_by_subclass: dict = {}
    sf_by_lvl_name_src: dict = {}
    for sf in ref["subclassFeature"]:
        if "_copy" in sf:
            continue
        cs = sf.get("classSource") or "PHB"
        key = (sf["className"], cs, sf["subclassShortName"], sf["subclassSource"])
        sf_by_subclass.setdefault(key, []).append(sf)
        sf_by_lvl_name_src.setdefault((sf["level"], sf["name"], sf["source"]), []).append(
            (sf["className"], cs, sf["subclassShortName"], sf["subclassSource"], sf)
        )
    idx["sf_by_subclass"] = sf_by_subclass
    idx["sf_by_lvl_name_src"] = sf_by_lvl_name_src

    return idx


def own_subclass_features(idx: dict, sc: dict) -> list:
    """subclassFeature entries linked to `sc` whose own `source` matches `sc`'s --
    i.e. the ones that are actually *this subclass's own* text. `idx["sf_by_subclass"]`
    groups by (className, classSource, shortName, subclassSource) alone, which also
    catches later books' bonus additions to an *existing* subclass (e.g. TCE's
    "Blessed Strikes" is filed under every Cleric domain, including PHB's; SCAG's
    "Elk"/"Tiger" are filed under PHB's Totem Warrior) -- those must stay out of the
    base subclass's own bundle and only surface via their own book's pass."""
    cs = sc.get("classSource") or "PHB"
    key = (sc["className"], cs, sc["shortName"], sc["source"])
    return [sf for sf in idx["sf_by_subclass"].get(key, []) if sf["source"] == sc["source"]]


def resolve_class_bundle(idx: dict, name: str, stub_source: str):
    cls = idx["classes"].get((name, stub_source))
    if cls is None:
        return None
    features = [cf for cf in idx["cf_by_class"].get((name, stub_source), []) if cf["source"] == stub_source]
    subclasses = [
        sc
        for (cn, cs, _short, src), sc in idx["subclasses"].items()
        if cn == name and cs == stub_source and src == stub_source
    ]
    sub_features = []
    for sc in subclasses:
        sub_features.extend(own_subclass_features(idx, sc))
    return {"class": cls, "classFeatures": features, "subclasses": subclasses, "subclassFeatures": sub_features}


def resolve_subclass_bundle(idx: dict, short_name: str, class_name: str, class_source: str, subclass_source: str):
    sc = idx["subclasses"].get((class_name, class_source, short_name, subclass_source))
    if sc is None:
        return None
    features = own_subclass_features(idx, sc)
    return {"subclass": sc, "subclassFeatures": features}


def remap(entry: dict, orig_source: str, book: str) -> dict:
    e = copy.deepcopy(entry)
    for key in ("source", "classSource", "subclassSource"):
        if e.get(key) == orig_source:
            e[key] = book
    return e


# --------------------------------------------------------------------------
# Regenerating classFeatures / subclassFeatures pipe-delimited reference lists
# --------------------------------------------------------------------------
def _parse_cf_ref(s: str, default_class_name: str):
    parts = s.split("|")
    name = parts[0]
    cn = parts[1] if len(parts) > 1 and parts[1] else default_class_name
    cs = parts[2] if len(parts) > 2 and parts[2] else "PHB"
    level = int(parts[3]) if len(parts) > 3 and parts[3] else None
    fs = parts[4] if len(parts) > 4 and parts[4] else cs
    return name, cn, cs, level, fs


def rebuild_class_features_refs(original_list, kept_keys, class_name, orig_source, book):
    out = []
    for item in original_list or []:
        is_obj = isinstance(item, dict)
        ref = item["classFeature"] if is_obj else item
        name, cn, cs, level, fs = _parse_cf_ref(ref, class_name)
        if (level, name, fs) not in kept_keys:
            continue
        new_cs = book if cs == orig_source else cs
        new_fs = book if fs == orig_source else fs
        new_ref = f"{name}|{cn}|{new_cs}|{level}|{new_fs}"
        if is_obj:
            out.append({**item, "classFeature": new_ref})
        else:
            out.append(new_ref)
    return out


def _parse_sf_ref(s: str, default_class_name: str, default_short_name: str):
    parts = s.split("|")
    name = parts[0]
    cn = parts[1] if len(parts) > 1 and parts[1] else default_class_name
    cs = parts[2] if len(parts) > 2 and parts[2] else "PHB"
    sn = parts[3] if len(parts) > 3 and parts[3] else default_short_name
    ss = parts[4] if len(parts) > 4 and parts[4] else "PHB"
    level = int(parts[5]) if len(parts) > 5 and parts[5] else None
    fs = parts[6] if len(parts) > 6 and parts[6] else ss
    return name, cn, cs, sn, ss, level, fs


def rebuild_subclass_features_refs(original_list, kept_keys, class_name, short_name, orig_class_source, orig_subclass_source, book):
    out = []
    for item in original_list or []:
        is_obj = isinstance(item, dict)
        ref = item["subclassFeature"] if is_obj else item
        name, cn, cs, sn, ss, level, fs = _parse_sf_ref(ref, class_name, short_name)
        if (level, name, fs) not in kept_keys:
            continue
        new_cs = book if cs == orig_class_source else cs
        new_ss = book if ss == orig_subclass_source else ss
        new_fs = book if fs == orig_subclass_source else fs
        new_ref = f"{name}|{cn}|{new_cs}|{sn}|{new_ss}|{level}|{new_fs}"
        if is_obj:
            out.append({**item, "subclassFeature": new_ref})
        else:
            out.append(new_ref)
    return out


# --------------------------------------------------------------------------
# Per-book extraction
# --------------------------------------------------------------------------
class BookResult:
    def __init__(self, source_code):
        self.source_code = source_code
        self.out = {"class": {}, "subclass": {}, "classFeature": {}, "subclassFeature": {}}
        self.provenance = {}
        self.unresolved_stubs = []  # (tag, uid, section)
        self.unresolved_minitoc = []  # (name, level, descriptor, section)
        self.unresolved_candidates = []  # (kind, name, className, level, source)

    def add(self, kind, entry, prov_key, section, origin, match, data_from=None):
        self.out[kind][prov_key] = entry
        prov = {"origin": origin, "match": match, "section": section}
        if data_from:
            prov["data_from"] = data_from
        self.provenance[f"{kind}:{prov_key}"] = prov


def process_book(source_code: str, text: str, idx: dict, ref: dict) -> BookResult:
    res = BookResult(source_code)
    lines = text.split("\n")

    # heading stack -> path per line (1-indexed), for section-id provenance
    stack: list = []
    line_path = [None] * (len(lines) + 2)
    for i, line in enumerate(lines, 1):
        m = HEADING_RE.match(line)
        if m:
            level = len(m.group(1))
            title = m.group(2).strip()
            stack = stack[: level - 1] + [title]
        line_path[i] = tuple(stack)

    def section_id_at(line_no: int) -> str:
        path = line_path[line_no] if 0 < line_no < len(line_path) else tuple(stack)
        if not path:
            return source_code
        return source_code + ":" + "/".join(slugify(h) for h in path)

    consumed_cf = set()  # (level, name, source) -- pre-remap identity
    consumed_sf = set()
    consumed_subclass = set()  # (className, classSource, shortName, source) -- pre-remap identity
    consumed_class = set()  # name -- pre-remap identity (class's own source is always stub_source here)

    def cf_key(cf: dict):
        """Fully-specific dedup key for a classFeature -- (level, name, source)
        alone collides across classes that happen to share a feature name at the
        same level (e.g. every class has its own "Ability Score Improvement" at
        level 4/PHB); Pass 1 doesn't consult this (it always adds unconditionally,
        keyed correctly in res.out/provenance by the full name|className|level
        string), but passes 2-4 use it to decide whether a candidate is already
        placed, so under-specifying it would wrongly skip a still-needed sibling."""
        return (cf["level"], cf["name"], cf["className"], cf["source"])

    def sf_key(sf: dict):
        """Fully-specific dedup key for a subclassFeature -- verified real bug this
        guards against: TCE's "Blessed Strikes" is one differently-sourced bonus
        feature filed under 15 different Cleric domains (Order/Peace/Twilight plus
        12 other-book domains) all at the same level/name/source; without
        subclassShortName+subclassSource in the key, placing the first one marked
        all 15 as "already handled" and silently dropped the other 14."""
        return (sf["level"], sf["name"], sf["subclassShortName"], sf["subclassSource"], sf["source"])

    # ---------------- PASS 1: data-rd-tag="class"/"subclass" stubs ----------------
    for m in TD_RE.finditer(text):
        attrs = m.group(1)
        tag_m = TAG_RE.search(attrs)
        if not tag_m:
            continue
        uid_m = UID_RE.search(attrs)
        line_no = text.count("\n", 0, m.start()) + 1
        section = section_id_at(line_no)
        tag = tag_m.group(1)
        uid = uid_m.group(1) if uid_m else ""

        if tag == "class":
            parts = uid.split("|")
            if len(parts) != 2 or not all(parts):
                res.unresolved_stubs.append((tag, uid, section))
                continue
            name, stub_source = parts
            bundle = resolve_class_bundle(idx, name, stub_source)
            if bundle is None:
                res.unresolved_stubs.append((tag, uid, section))
                continue
            data_from = stub_source if stub_source != source_code else None

            cf_keys = {(cf["level"], cf["name"], cf["source"]) for cf in bundle["classFeatures"]}
            cls_r = remap(bundle["class"], stub_source, source_code)
            cls_r["classFeatures"] = rebuild_class_features_refs(
                bundle["class"].get("classFeatures", []), cf_keys, name, stub_source, source_code
            )
            res.add("class", cls_r, name, section, "5etools-src", "stub", data_from)
            consumed_class.add(name)

            for cf in bundle["classFeatures"]:
                consumed_cf.add(cf_key(cf))
                cf_r = remap(cf, stub_source, source_code)
                res.add(
                    "classFeature", cf_r, f"{cf['name']}|{name}|{cf['level']}",
                    section, "5etools-src", "stub", data_from,
                )

            for sc in bundle["subclasses"]:
                cs = sc.get("classSource") or "PHB"
                sf_list = own_subclass_features(idx, sc)
                sf_keys = {(sf["level"], sf["name"], sf["source"]) for sf in sf_list}
                sc_r = remap(sc, stub_source, source_code)
                sc_r["subclassFeatures"] = rebuild_subclass_features_refs(
                    sc.get("subclassFeatures", []), sf_keys, sc["className"], sc["shortName"], cs, sc["source"], source_code,
                )
                res.add("subclass", sc_r, f"{sc['name']}|{sc['className']}", section, "5etools-src", "stub", data_from)
                consumed_subclass.add((sc["className"], cs, sc["shortName"], sc["source"]))
                for sf in sf_list:
                    consumed_sf.add(sf_key(sf))
                    sf_r = remap(sf, stub_source, source_code)
                    res.add(
                        "subclassFeature", sf_r,
                        f"{sf['name']}|{sf['className']}|{sf['subclassShortName']}|{sf['level']}",
                        section, "5etools-src", "stub", data_from,
                    )

        elif tag == "subclass":
            parts = uid.split("|")
            if len(parts) != 4 or not parts[0] or not parts[1] or not parts[3]:
                res.unresolved_stubs.append((tag, uid, section))
                continue
            short_name, class_name, class_source, subclass_source = parts
            class_source = class_source or "PHB"
            bundle = resolve_subclass_bundle(idx, short_name, class_name, class_source, subclass_source)
            if bundle is None:
                res.unresolved_stubs.append((tag, uid, section))
                continue
            data_from = subclass_source if subclass_source != source_code else None
            sc = bundle["subclass"]
            sf_list = bundle["subclassFeatures"]
            sf_keys = {(sf["level"], sf["name"], sf["source"]) for sf in sf_list}
            sc_r = remap(sc, subclass_source, source_code)
            sc_r["subclassFeatures"] = rebuild_subclass_features_refs(
                sc.get("subclassFeatures", []), sf_keys, class_name, short_name, class_source, subclass_source, source_code,
            )
            res.add("subclass", sc_r, f"{sc['name']}|{class_name}", section, "5etools-src", "stub", data_from)
            consumed_subclass.add((class_name, class_source, short_name, subclass_source))
            for sf in sf_list:
                consumed_sf.add(sf_key(sf))
                sf_r = remap(sf, subclass_source, source_code)
                res.add(
                    "subclassFeature", sf_r,
                    f"{sf['name']}|{class_name}|{sf['subclassShortName']}|{sf['level']}",
                    section, "5etools-src", "stub", data_from,
                )

    # ---------------- PASS 2: bare "Name (*Nth-level X feature*)" lines ----------------
    for i, raw_line in enumerate(lines, 1):
        line = LEADING_TAG_RE.sub("", raw_line.strip()).strip()
        if not line or "feature" not in line.lower():
            continue
        m = MINITOC_RE.match(line)
        if not m:
            continue
        name, level_s, descriptor = m.groups()
        name = name.strip()
        level = int(level_s)
        section = section_id_at(i)
        found_any = False

        for cn, _cs, cf in idx["cf_by_lvl_name_src"].get((level, name, source_code), []):
            if cn.lower() == descriptor.lower():
                key = cf_key(cf)
                if key not in consumed_cf:
                    consumed_cf.add(key)
                    res.add("classFeature", copy.deepcopy(cf), f"{name}|{cn}|{level}", section, "5etools-src", "table-mention")
                found_any = True

        for cn, _cs, short, _ssrc, sf in idx["sf_by_lvl_name_src"].get((level, name, source_code), []):
            if cn.lower() == descriptor.lower() or short == descriptor:
                key = sf_key(sf)
                if key not in consumed_sf:
                    consumed_sf.add(key)
                    res.add(
                        "subclassFeature", copy.deepcopy(sf), f"{name}|{cn}|{short}|{level}",
                        section, "5etools-src", "table-mention",
                    )
                found_any = True

        if not found_any:
            res.unresolved_minitoc.append((name, level, descriptor, section))

    # ---------------- PASS 2.5 / 3: table-mention fallback, class-evidenced ----------------
    # A few books (confirmed: DMG, EGW, XGE) have a subclass chapter whose crunch never
    # survived capture at all -- not even a dead stub div -- but the subclass's own full
    # name still appears in real text: as a "### ClassName: SubclassName" heading (DMG),
    # as flavor prose directly under a "## ClassName" heading (EGW), or as a row of a
    # "new subclass options" summary table that also names the class in the same row
    # (XGE). A bare name search for these (and for individual orphan features such as
    # SCAG's Totem Warrior "Elk"/"Tiger" additions or TCE's "Maneuver Options") is unsafe
    # on its own: verified real false positive -- DMG's "Dread Lord" Zhentarim faction
    # rank, in an unrelated title-generator table, happens to share a name with the
    # Oathbreaker paladin's capstone. So a mention is only trusted when the class it
    # belongs to is independently evidenced right there: either the heading stack at that
    # point names the class, or the very same line does -- as a table row (XGE) or as
    # plain prose naming the class right next to the subclass (GGR/MOT: "a cleric
    # chooses a Divine Domain. This source adds the Order Domain...").
    def class_evidenced(line_no: int, class_name: str) -> bool:
        path = line_path[line_no] if 0 < line_no < len(line_path) else tuple(stack)
        if any(class_name.lower() in h.lower() for h in path):
            return True
        line_text = lines[line_no - 1] if 0 < line_no <= len(lines) else ""
        return class_name.lower() in line_text.lower()

    def first_evidenced_line(name: str, class_name: str):
        pat = re.compile(r"\b" + re.escape(name) + r"\b")
        for mm in pat.finditer(text):
            line_no = text.count("\n", 0, mm.start()) + 1
            if class_evidenced(line_no, class_name):
                return line_no
        return None

    def nearby_text(line_no: int, before: int = 25, after: int = 3) -> str:
        lo = max(0, line_no - 1 - before)
        hi = min(len(lines), line_no + after)
        return "\n".join(lines[lo:hi])

    def first_evidenced_line_for_subclass_feature(sf: dict):
        """Like first_evidenced_line, but for a feature belonging to an *existing*
        subclass that this book only adds an option to (e.g. SCAG's Totem Warrior
        "Elk"/"Tiger"): className rarely re-appears right at the mention (the
        surrounding section is about the parent subclass, not restated by class
        name), so also accept a match whose immediate surrounding lines name the
        parent subclass itself (verified real case: SCAG's Uthgardt/totem table is
        preceded, a few lines up, by "...correspond to the spirits of the Path of
        the Totem Warrior...")."""
        cs = sf.get("classSource") or "PHB"
        parent = idx["subclasses"].get((sf["className"], cs, sf["subclassShortName"], sf["subclassSource"]))
        pat = re.compile(r"\b" + re.escape(sf["name"]) + r"\b")
        for mm in pat.finditer(text):
            line_no = text.count("\n", 0, mm.start()) + 1
            if class_evidenced(line_no, sf["className"]):
                return line_no
            if parent is not None:
                ctx = nearby_text(line_no)
                if parent["name"] in ctx or parent["shortName"] in ctx:
                    return line_no
        return None

    # 2.5: whole subclasses named (no stub at all) but class-evidenced.
    for sc in ref["subclass"]:
        if sc.get("source") != source_code or "_copy" in sc or "subclassFeatures" not in sc:
            continue
        cs = sc.get("classSource") or "PHB"
        key = (sc["className"], cs, sc["shortName"], sc["source"])
        if key in consumed_subclass:
            continue
        line_no = first_evidenced_line(sc["name"], sc["className"])
        if line_no is None:
            continue
        section = section_id_at(line_no)
        sf_list = own_subclass_features(idx, sc)
        sf_keys = {(sf["level"], sf["name"], sf["source"]) for sf in sf_list}
        sc_r = copy.deepcopy(sc)
        sc_r["subclassFeatures"] = rebuild_subclass_features_refs(
            sc.get("subclassFeatures", []), sf_keys, sc["className"], sc["shortName"], cs, sc["source"], source_code,
        )
        res.add("subclass", sc_r, f"{sc['name']}|{sc['className']}", section, "5etools-src", "table-mention")
        consumed_subclass.add(key)
        for sf in sf_list:
            consumed_sf.add(sf_key(sf))
            res.add(
                "subclassFeature", copy.deepcopy(sf),
                f"{sf['name']}|{sf['className']}|{sf['subclassShortName']}|{sf['level']}",
                section, "5etools-src", "table-mention",
            )

    # 2.5b: subclasses canonically filed under a *different* book, with no stub here
    # either, but genuinely reprinted/introduced by name in this book's own prose (no
    # Markdown stub exists anywhere for these -- verified real cases: GGR's "This
    # source adds the Order Domain..."/"...Circle of Spores..." and MOT's "...College
    # of Eloquence for bards and the Oath of Glory for paladins..." -- both confirmed,
    # not coincidence, by the canonical data's own `otherSources` cross-reference).
    for sc in ref["subclass"]:
        if sc.get("source") == source_code or "_copy" in sc or "subclassFeatures" not in sc:
            continue
        other_sources = {o.get("source") for o in (sc.get("otherSources") or [])}
        if source_code not in other_sources:
            continue
        prov_key = f"{sc['name']}|{sc['className']}"
        if prov_key in res.out["subclass"]:
            continue
        line_no = first_evidenced_line(sc["name"], sc["className"])
        if line_no is None:
            continue
        section = section_id_at(line_no)
        cs = sc.get("classSource") or "PHB"
        sf_list = own_subclass_features(idx, sc)
        sf_keys = {(sf["level"], sf["name"], sf["source"]) for sf in sf_list}
        sc_r = remap(sc, sc["source"], source_code)
        sc_r["subclassFeatures"] = rebuild_subclass_features_refs(
            sc.get("subclassFeatures", []), sf_keys, sc["className"], sc["shortName"], cs, sc["source"], source_code,
        )
        res.add("subclass", sc_r, prov_key, section, "5etools-src", "table-mention", sc["source"])
        for sf in sf_list:
            sf_r = remap(sf, sc["source"], source_code)
            res.add(
                "subclassFeature", sf_r,
                f"{sf['name']}|{sf['className']}|{sf['subclassShortName']}|{sf['level']}",
                section, "5etools-src", "table-mention", sc["source"],
            )

    # 3: individual orphan classFeature/subclassFeature mentions, class-evidenced.
    for cf in ref["classFeature"]:
        if cf.get("source") != source_code or "_copy" in cf:
            continue
        key = cf_key(cf)
        if key in consumed_cf:
            continue
        line_no = first_evidenced_line(cf["name"], cf["className"])
        if line_no is not None:
            section = section_id_at(line_no)
            consumed_cf.add(key)
            res.add(
                "classFeature", copy.deepcopy(cf), f"{cf['name']}|{cf['className']}|{cf['level']}",
                section, "5etools-src", "table-mention",
            )
        else:
            res.unresolved_candidates.append(("classFeature", cf["name"], cf["className"], cf["level"], cf["source"]))

    for sf in ref["subclassFeature"]:
        if sf.get("source") != source_code or "_copy" in sf:
            continue
        key = sf_key(sf)
        if key in consumed_sf:
            continue
        line_no = first_evidenced_line_for_subclass_feature(sf)
        if line_no is not None:
            section = section_id_at(line_no)
            consumed_sf.add(key)
            res.add(
                "subclassFeature", copy.deepcopy(sf),
                f"{sf['name']}|{sf['className']}|{sf['subclassShortName']}|{sf['level']}",
                section, "5etools-src", "table-mention",
            )
        else:
            res.unresolved_candidates.append(
                ("subclassFeature", sf["name"], sf["className"], sf["level"], sf["source"])
            )

    # ---------------- PASS 4: source-complete catch-all ----------------
    # Final completeness net (per Main): once every stub/mini-toc/table-mention has
    # been resolved, pull in any remaining record of our four types whose own
    # `source` is this book's code regardless of whether the Markdown shows any
    # trace of it at all -- some chapters were captured as a single pointer
    # sentence with no named mention (e.g. a bare "See the Spells chapter"), so
    # nothing short of this would ever surface them. Verified (by exhaustively
    # diffing every book's reference-data records against passes 1-3 output
    # across the full 51-book corpus) to add exactly two records: TCE's "Deft
    # Explorer Improvement" (levels 6 and 10), which genuinely has no textual
    # trace anywhere in TCE's Markdown at all, not even the name.
    no_section = source_code  # no textual anchor exists; book-level fallback id

    for c in ref["class"]:
        if c.get("source") != source_code or "_copy" in c or c["name"] in consumed_class:
            continue
        bundle = resolve_class_bundle(idx, c["name"], source_code)
        if bundle is None:
            continue
        cf_keys = {(cf["level"], cf["name"], cf["source"]) for cf in bundle["classFeatures"]}
        cls_r = copy.deepcopy(bundle["class"])
        cls_r["classFeatures"] = rebuild_class_features_refs(
            bundle["class"].get("classFeatures", []), cf_keys, c["name"], source_code, source_code
        )
        res.add("class", cls_r, c["name"], no_section, "5etools-src", "source-complete")
        consumed_class.add(c["name"])
        for cf in bundle["classFeatures"]:
            consumed_cf.add(cf_key(cf))
            res.add(
                "classFeature", copy.deepcopy(cf), f"{cf['name']}|{c['name']}|{cf['level']}",
                no_section, "5etools-src", "source-complete",
            )
        for sc in bundle["subclasses"]:
            cs = sc.get("classSource") or "PHB"
            key = (sc["className"], cs, sc["shortName"], sc["source"])
            sf_list = own_subclass_features(idx, sc)
            sf_keys = {(sf["level"], sf["name"], sf["source"]) for sf in sf_list}
            sc_r = copy.deepcopy(sc)
            sc_r["subclassFeatures"] = rebuild_subclass_features_refs(
                sc.get("subclassFeatures", []), sf_keys, sc["className"], sc["shortName"], cs, sc["source"], source_code,
            )
            res.add("subclass", sc_r, f"{sc['name']}|{sc['className']}", no_section, "5etools-src", "source-complete")
            consumed_subclass.add(key)
            for sf in sf_list:
                consumed_sf.add(sf_key(sf))
                res.add(
                    "subclassFeature", copy.deepcopy(sf),
                    f"{sf['name']}|{sf['className']}|{sf['subclassShortName']}|{sf['level']}",
                    no_section, "5etools-src", "source-complete",
                )

    for sc in ref["subclass"]:
        if sc.get("source") != source_code or "_copy" in sc or "subclassFeatures" not in sc:
            continue
        cs = sc.get("classSource") or "PHB"
        key = (sc["className"], cs, sc["shortName"], sc["source"])
        if key in consumed_subclass:
            continue
        sf_list = own_subclass_features(idx, sc)
        sf_keys = {(sf["level"], sf["name"], sf["source"]) for sf in sf_list}
        sc_r = copy.deepcopy(sc)
        sc_r["subclassFeatures"] = rebuild_subclass_features_refs(
            sc.get("subclassFeatures", []), sf_keys, sc["className"], sc["shortName"], cs, sc["source"], source_code,
        )
        res.add("subclass", sc_r, f"{sc['name']}|{sc['className']}", no_section, "5etools-src", "source-complete")
        consumed_subclass.add(key)
        for sf in sf_list:
            consumed_sf.add(sf_key(sf))
            res.add(
                "subclassFeature", copy.deepcopy(sf),
                f"{sf['name']}|{sf['className']}|{sf['subclassShortName']}|{sf['level']}",
                no_section, "5etools-src", "source-complete",
            )

    for cf in ref["classFeature"]:
        if cf.get("source") != source_code or "_copy" in cf:
            continue
        key = cf_key(cf)
        if key in consumed_cf:
            continue
        consumed_cf.add(key)
        res.add(
            "classFeature", copy.deepcopy(cf), f"{cf['name']}|{cf['className']}|{cf['level']}",
            no_section, "5etools-src", "source-complete",
        )
        res.unresolved_candidates = [c for c in res.unresolved_candidates if not (c[0] == "classFeature" and c[1] == cf["name"] and c[3] == cf["level"])]

    for sf in ref["subclassFeature"]:
        if sf.get("source") != source_code or "_copy" in sf:
            continue
        key = sf_key(sf)
        if key in consumed_sf:
            continue
        consumed_sf.add(key)
        res.add(
            "subclassFeature", copy.deepcopy(sf),
            f"{sf['name']}|{sf['className']}|{sf['subclassShortName']}|{sf['level']}",
            no_section, "5etools-src", "source-complete",
        )
        res.unresolved_candidates = [
            c for c in res.unresolved_candidates
            if not (c[0] == "subclassFeature" and c[1] == sf["name"] and c[3] == sf["level"])
        ]
    return res


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------
def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    allow = schema_allowlists()
    ref = load_reference()
    idx = build_indices(ref)
    sources_meta = json.loads(SOURCES_JSON.read_text(encoding="utf-8"))
    books = sources_meta["books"]

    report = {"missing_book_json": [], "per_book": {}}

    for b in books:
        source_code = b["source"]
        md_path = BOOKS_MD_DIR / b["file"]
        if not md_path.exists():
            report["per_book"][source_code] = {"error": f"markdown not found: {md_path}"}
            continue
        text = md_path.read_text(encoding="utf-8")

        res = process_book(source_code, text, idx, ref)
        total = sum(len(v) for v in res.out.values())
        if total == 0:
            continue  # nothing of this type in this book; no shard written

        book_json_path = BOOKS_JSON_DIR / f"{source_code}.json"
        if not book_json_path.exists():
            report["missing_book_json"].append(source_code)
            continue
        book_json = json.loads(book_json_path.read_text(encoding="utf-8"))
        meta = book_json["_meta"]

        shard = {
            "_meta": {
                "sources": meta["sources"],
                "edition": meta.get("edition", "classic"),
                "dateAdded": meta["dateAdded"],
                "dateLastModified": meta["dateLastModified"],
            }
        }
        for kind in ("class", "subclass", "classFeature", "subclassFeature"):
            items = list(res.out[kind].values())
            if not items:
                continue
            items = [filter_props(it, allow[kind]) for it in items]
            if kind in ("class", "subclass"):
                items.sort(key=lambda e: e["name"])
            else:
                items.sort(key=lambda e: (e["className"], e.get("subclassShortName", ""), e["level"], e["name"]))
            shard[kind] = items

        (OUT_DIR / f"{source_code}.json").write_text(
            json.dumps(shard, indent="\t", ensure_ascii=False) + "\n", encoding="utf-8"
        )
        (OUT_DIR / f"{source_code}.provenance.json").write_text(
            json.dumps(res.provenance, indent="\t", ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
        )

        report["per_book"][source_code] = {
            "class": len(res.out["class"]),
            "subclass": len(res.out["subclass"]),
            "classFeature": len(res.out["classFeature"]),
            "subclassFeature": len(res.out["subclassFeature"]),
            "stub_count": sum(1 for p in res.provenance.values() if p["match"] == "stub"),
            "table_mention_count": sum(1 for p in res.provenance.values() if p["match"] == "table-mention"),
            "cross_book_count": sum(1 for p in res.provenance.values() if "data_from" in p),
            "source_complete_count": sum(1 for p in res.provenance.values() if p["match"] == "source-complete"),
            "unresolved_stubs": [{"tag": t, "uid": u, "section": s} for (t, u, s) in res.unresolved_stubs],
            "unresolved_minitoc_mentions": [
                {"name": n, "level": lv, "descriptor": d, "section": s} for (n, lv, d, s) in res.unresolved_minitoc
            ],
            "candidates_not_converted": len(res.unresolved_candidates),
            "candidates_detail": [
                {"kind": k, "name": n, "className": cn, "level": lv, "source": src}
                for (k, n, cn, lv, src) in res.unresolved_candidates
            ],
        }

    (OUT_DIR / "_extraction_report.json").write_text(
        json.dumps(report, indent="\t", ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps({"generated": int(time.time()), "books_with_output": len(report["per_book"])}, indent=2))


if __name__ == "__main__":
    main()
