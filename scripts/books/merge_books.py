#!/usr/bin/env python3
"""Wave 3: final assembly of the 51-book 5etools conversion.

Merges wave 1 (`ref/5etools/books/<SOURCE>.json`: book/bookData) with wave 2's
per-type shards (`ref/5etools/shards/<group>/<SOURCE>.json` + their
`.provenance.json` sidecars) into one homebrew-style file per book under
`ref/5etools/merged/<SOURCE>.json`, restores `page` numbers for entities whose
provenance origin is `5etools-src`, and checks `{@tag Name|Source}` /
`statblock` reference integrity against our own merged corpus and the
official data mirror (`ref/5etools-src/data/`).

Does not read or embed any book prose itself -- it only moves already-converted
JSON values between files and consults small official lookup *records*
(name/source/page/otherSources) for page restoration and existence checks.

Outputs:
  ref/5etools/merged/<SOURCE>.json              one merged file per book
  ref/5etools/merged/provenance/<SOURCE>.json   combined provenance sidecars
  ref/5etools/merged/_index.json                per-book entity/origin/page counts
  ref/5etools/merged/_references.json           reference-integrity report

Python 3.9 stdlib only. Run: python3 scripts/books/merge_books.py
"""
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BOOKS_DIR = REPO_ROOT / "ref/5etools/books"
SHARDS_DIR = REPO_ROOT / "ref/5etools/shards"
OFFICIAL_DIR = REPO_ROOT / "ref/5etools-src/data"
SOURCES_JSON = REPO_ROOT / "ref/5etools/sources.json"
OUT_DIR = REPO_ROOT / "ref/5etools/merged"
PROV_OUT_DIR = OUT_DIR / "provenance"

GEN_TIME = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

SHARD_GROUPS = ["monsters", "items", "spells", "charoptions", "classes", "world", "recipes"]

# Every entity-array key wave 2 can emit, mapped to the one shard group that
# owns it (verified empirically against the real shard output -- no type name
# is ever emitted by two different groups).
TYPE_GROUP = {
    "monster": "monsters", "legendaryGroup": "monsters",
    "item": "items", "baseitem": "items", "magicvariant": "items", "itemGroup": "items",
    "spell": "spells",
    "race": "charoptions", "subrace": "charoptions", "background": "charoptions", "feat": "charoptions",
    "optionalfeature": "charoptions", "charoption": "charoptions", "boon": "charoptions",
    "class": "classes", "subclass": "classes", "classFeature": "classes", "subclassFeature": "classes",
    "action": "world", "card": "world", "condition": "world", "cult": "world", "deck": "world",
    "deity": "world", "disease": "world", "hazard": "world", "language": "world", "object": "world",
    "reward": "world", "status": "world", "table": "world", "trap": "world", "variantrule": "world",
    "vehicle": "world",
    "recipe": "recipes", "recipeFluff": "recipes",
}

# Fields (besides name+source) that disambiguate same-named records of a type.
# Discovered from each wave-2 extractor's own provenance-key convention and
# confirmed against the real schema (className/level/etc. are never rewritten
# on cross-book reprints, unlike the *Source fields, so they're safe to match
# directly between a shard entity and an official/corpus record).
IDENTITY_FIELDS = {
    "classFeature": ["className", "level"],
    "subclassFeature": ["className", "subclassShortName", "level"],
    "subclass": ["className"],
    "subrace": ["raceName"],
    "card": ["set"],
    "deity": ["pantheon"],
}

# `action` is the only one of our 36 types whose brew schema REQUIRES `page`
# (verified against ref/5etools/tooling .../schema/brew/actions.json); wave 2
# already placates that with a page:0 placeholder when it has nothing better.
# We never delete/null an existing page -- only overwrite it with a real
# looked-up value, so this never needs special-casing in the code below.


def norm_name(s):
    return (s or "").strip().lower()


def norm_source(s):
    return (s or "").strip().lower()


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# magicvariant quirk: its `source`/`page`/`otherSources` live under `inherits`
# (its own top-level `source` is only required on the alternate `_copy`
# branch) -- these helpers transparently fall back to `inherits` so every
# other function can treat all types uniformly.
# ---------------------------------------------------------------------------

def effective_source(entity):
    return entity.get("source") or (entity.get("inherits") or {}).get("source")


def effective_page(entity):
    if entity.get("page") is not None:
        return entity.get("page")
    return (entity.get("inherits") or {}).get("page")


def set_page(entity, value):
    if "source" not in entity and isinstance(entity.get("inherits"), dict):
        entity["inherits"]["page"] = value
    else:
        entity["page"] = value


def effective_other_sources(entity):
    res = []
    res += list(entity.get("otherSources") or [])
    res += list(entity.get("additionalSources") or [])
    inh = entity.get("inherits") or {}
    res += list(inh.get("otherSources") or [])
    res += list(inh.get("additionalSources") or [])
    return res


# ---------------------------------------------------------------------------
# Official-data index: {type: {normalized_name: [record, ...]}}
# ---------------------------------------------------------------------------
SOURCE_CANON = {}


def note_source(s):
    if s and norm_source(s) not in SOURCE_CANON:
        SOURCE_CANON[norm_source(s)] = s


def add_records(index, type_name, records):
    bucket = index.setdefault(type_name, {})
    for r in records:
        name = r.get("name")
        if not name:
            continue
        note_source(effective_source(r))
        bucket.setdefault(norm_name(name), []).append(r)
        # Barbarian-style subclasses (and similar) are tagged/linked by their
        # short display name (e.g. "Giant" for "Path of the Giant"), which can
        # differ from the full `name` -- index under both so lookups by
        # either succeed.
        if type_name == "subclass":
            sn = r.get("shortName")
            if sn and norm_name(sn) != norm_name(name):
                bucket.setdefault(norm_name(sn), []).append(r)


SIMPLE_OFFICIAL_FILES = {
    "items.json": ["item", "itemGroup"],
    "items-base.json": ["baseitem"],
    "magicvariants.json": ["magicvariant"],
    "races.json": ["race", "subrace"],
    "backgrounds.json": ["background"],
    "feats.json": ["feat"],
    "optionalfeatures.json": ["optionalfeature"],
    "charcreationoptions.json": ["charoption"],
    "cultsboons.json": ["cult", "boon"],
    "recipes.json": ["recipe"],
    "fluff-recipes.json": ["recipeFluff"],
    "actions.json": ["action"],
    "conditionsdiseases.json": ["condition", "disease", "status"],
    "deities.json": ["deity"],
    "trapshazards.json": ["trap", "hazard"],
    "languages.json": ["language"],
    "objects.json": ["object"],
    "rewards.json": ["reward"],
    "tables.json": ["table"],
    "variantrules.json": ["variantrule"],
    "vehicles.json": ["vehicle"],
    "decks.json": ["deck", "card"],
}


def build_official_index():
    idx = {}
    for f in sorted((OFFICIAL_DIR / "bestiary").glob("bestiary-*.json")):
        d = load_json(f)
        add_records(idx, "monster", d.get("monster", []))
    lg = load_json(OFFICIAL_DIR / "bestiary/legendarygroups.json")
    add_records(idx, "legendaryGroup", lg.get("legendaryGroup", []))

    for f in sorted((OFFICIAL_DIR / "class").glob("class-*.json")):
        d = load_json(f)
        for t in ("class", "subclass", "classFeature", "subclassFeature"):
            add_records(idx, t, d.get(t, []))

    for f in sorted((OFFICIAL_DIR / "spells").glob("spells-*.json")):
        d = load_json(f)
        add_records(idx, "spell", d.get("spell", []))

    for fname, types in SIMPLE_OFFICIAL_FILES.items():
        d = load_json(OFFICIAL_DIR / fname)
        for t in types:
            add_records(idx, t, d.get(t, []))

    # tables.json (13 entries) is a small legacy subset; gendata-tables.json
    # is the site's generated, comprehensive table index (2368+) -- union both.
    gd = load_json(OFFICIAL_DIR / "generated/gendata-tables.json")
    add_records(idx, "table", gd.get("table", []))

    return idx


def record_matches(r, source, extra_wanted):
    if source is not None and norm_source(effective_source(r)) != norm_source(source):
        return False
    for f, want in (extra_wanted or {}).items():
        if want is None:
            continue
        have = r.get(f)
        if have is None:
            continue
        if norm_name(str(want)) != norm_name(str(have)):
            return False
    return True


def find_candidates(index, type_name, name, source, extra_wanted=None):
    bucket = index.get(type_name, {})
    cands = bucket.get(norm_name(name), [])
    if not cands:
        return []
    return [r for r in cands if record_matches(r, source, extra_wanted)]


def exists_in(index, type_name, name, source, extra):
    return bool(find_candidates(index, type_name, name, source, extra))


# ---------------------------------------------------------------------------
# Per-book merge: book/bookData + every shard array, with duplicate detection.
# ---------------------------------------------------------------------------

def dedup_key(type_name, ent):
    extra = tuple(
        norm_name(str(ent.get(f))) if ent.get(f) is not None else None
        for f in IDENTITY_FIELDS.get(type_name, [])
    )
    return (type_name, norm_name(ent.get("name")), norm_source(effective_source(ent))) + extra


def merge_one_book(src):
    book_doc = load_json(BOOKS_DIR / f"{src}.json")
    merged = {
        "_meta": dict(book_doc["_meta"]),
        "book": book_doc.get("book", []),
        "bookData": book_doc.get("bookData", []),
    }
    dup_log = []
    seen_keys = {}
    combined_prov = {}

    for group in SHARD_GROUPS:
        shard_path = SHARDS_DIR / group / f"{src}.json"
        prov_path = SHARDS_DIR / group / f"{src}.provenance.json"
        if shard_path.exists():
            shard_doc = load_json(shard_path)
            for type_name, entities in shard_doc.items():
                if type_name == "_meta" or not isinstance(entities, list):
                    continue
                out_list = merged.setdefault(type_name, [])
                for ent in entities:
                    key = dedup_key(type_name, ent)
                    if key in seen_keys:
                        dup_log.append({
                            "type": type_name, "name": ent.get("name"),
                            "source": effective_source(ent), "group": group,
                            "keptFromGroup": seen_keys[key],
                        })
                        continue
                    seen_keys[key] = group
                    out_list.append(ent)
        if prov_path.exists():
            combined_prov[group] = load_json(prov_path)

    if merged.get("recipeFluff"):
        merged["_meta"]["internalCopies"] = ["recipeFluff"]

    return merged, dup_log, combined_prov


# ---------------------------------------------------------------------------
# Provenance lookup: reconstruct, per shard group, the same key an extractor
# used to write its sidecar, straight from the merged entity's own fields
# (rather than parsing key strings back apart).
# ---------------------------------------------------------------------------

def get_provenance_record(group, prov_doc, type_name, entity):
    if prov_doc is None:
        return None
    name = entity.get("name")
    if group == "monsters":
        if type_name == "monster":
            return prov_doc.get(name)
        if type_name == "legendaryGroup":
            return prov_doc.get(f"legendaryGroup:{name}")
        return None
    if group == "items":
        return prov_doc.get("entities", {}).get(type_name, {}).get(name)
    if group == "spells":
        return prov_doc.get(name)
    if group == "classes":
        if type_name == "class":
            key = name
        elif type_name == "subclass":
            key = f"{name}|{entity.get('className')}"
        elif type_name == "classFeature":
            key = f"{name}|{entity.get('className')}|{entity.get('level')}"
        elif type_name == "subclassFeature":
            key = f"{name}|{entity.get('className')}|{entity.get('subclassShortName')}|{entity.get('level')}"
        else:
            return None
        return prov_doc.get(f"{type_name}:{key}")
    if group == "charoptions":
        key = f"{name}|{entity.get('raceName')}" if type_name == "subrace" else name
        return prov_doc.get(f"{type_name}:{key}")
    if group == "world":
        sub = prov_doc.get(type_name, {})
        if type_name == "card":
            rec = sub.get(f"{name}|{entity.get('set')}")
            return rec if rec is not None else sub.get(name)
        return sub.get(name)
    if group == "recipes":
        return prov_doc.get(name) if type_name == "recipe" else None
    return None


def get_data_from(prov):
    if not prov:
        return None
    return prov.get("data_from") or prov.get("dataFrom")


# ---------------------------------------------------------------------------
# Page restoration
# ---------------------------------------------------------------------------
PAGE_STATS_KEYS = [
    "total", "eligible", "restored",
    "miss_no_record", "miss_no_page_value", "miss_ambiguous", "miss_reprint_no_othersources",
]


def new_page_stats():
    return {k: 0 for k in PAGE_STATS_KEYS}


def restore_page_for_entity(official_index, type_name, entity, book_src, prov, stats, miss_log):
    stats["total"] += 1
    if not prov or prov.get("origin") != "5etools-src":
        return
    stats["eligible"] += 1
    data_from = get_data_from(prov)
    search_source = data_from or book_src
    extra = {f: entity.get(f) for f in IDENTITY_FIELDS.get(type_name, [])}
    cands = find_candidates(official_index, type_name, entity.get("name"), search_source, extra)

    if not cands:
        stats["miss_no_record"] += 1
        miss_log.append({"type": type_name, "name": entity.get("name"), "book": book_src,
                          "searchSource": search_source, "reason": "no-official-record"})
        return

    if norm_source(search_source) == norm_source(book_src):
        pages = sorted({effective_page(c) for c in cands if effective_page(c) is not None})
        if not pages:
            stats["miss_no_page_value"] += 1
            return
        if len(pages) > 1:
            stats["miss_ambiguous"] += 1
            miss_log.append({"type": type_name, "name": entity.get("name"), "book": book_src,
                              "searchSource": search_source, "reason": f"ambiguous-direct-pages={pages}"})
            return
        set_page(entity, pages[0])
        stats["restored"] += 1
        return

    # Reprint case: the matching official record lives under `data_from`;
    # only use its page *for this book* if it documents one via
    # otherSources/additionalSources -- never invent one.
    pages = set()
    for c in cands:
        for e in effective_other_sources(c):
            if norm_source(e.get("source")) == norm_source(book_src) and e.get("page") is not None:
                pages.add(e["page"])
    if not pages:
        stats["miss_reprint_no_othersources"] += 1
        miss_log.append({"type": type_name, "name": entity.get("name"), "book": book_src,
                          "searchSource": search_source, "reason": "no-otherSources-entry-for-this-book"})
        return
    if len(pages) > 1:
        stats["miss_ambiguous"] += 1
        miss_log.append({"type": type_name, "name": entity.get("name"), "book": book_src,
                          "searchSource": search_source, "reason": f"ambiguous-reprint-pages={sorted(pages)}"})
        return
    set_page(entity, pages.pop())
    stats["restored"] += 1


def restore_pages_for_book(official_index, merged, src, combined_prov, stats, miss_log):
    for type_name, entities in merged.items():
        if type_name in ("_meta", "book", "bookData") or not isinstance(entities, list):
            continue
        group = TYPE_GROUP.get(type_name)
        prov_doc = combined_prov.get(group) if group else None
        for ent in entities:
            prov = get_provenance_record(group, prov_doc, type_name, ent)
            restore_page_for_entity(official_index, type_name, ent, src, prov, stats, miss_log)


# ---------------------------------------------------------------------------
# Reference integrity: {@tag Name|Source} strings + statblock nodes.
#
# Tag argument layouts and default sources are taken verbatim from the
# project's own renderdemo documentation (ref/5etools-src/data/renderdemo.json
# prose, e.g. "Spells: {@spell acid splash} assumes PHB by default..."),
# cross-checked against real tag usage in our corpus. Formatting/mechanical
# tags (@b, @dice, @hit, @skill, ...) and navigational tags (@book, @adventure,
# @itemProperty) are out of scope -- they don't reference one of our 36
# extracted entity types.
# ---------------------------------------------------------------------------
SIMPLE_TAG_DEFAULTS = {
    "spell": (["spell"], "PHB"),
    "item": (["item", "baseitem", "magicvariant", "itemGroup"], "DMG"),
    "creature": (["monster"], "MM"),
    "legroup": (["legendaryGroup"], "MM"),
    "background": (["background"], "PHB"),
    "race": (["race"], "PHB"),
    "optfeature": (["optionalfeature"], "PHB"),
    "condition": (["condition"], "PHB"),
    "disease": (["disease"], "DMG"),
    "reward": (["reward"], "DMG"),
    "feat": (["feat"], "PHB"),
    "object": (["object"], "DMG"),
    "boon": (["boon"], "MTF"),
    "cult": (["cult"], "MTF"),
    "trap": (["trap"], "DMG"),
    "hazard": (["hazard"], "DMG"),
    "variantrule": (["variantrule"], "DMG"),
    "vehicle": (["vehicle"], "GoS"),
    "table": (["table"], "DMG"),
    "action": (["action"], "PHB"),
    "language": (["language"], "PHB"),
    "charoption": (["charoption"], "MOT"),
    "deck": (["deck"], "DMG"),
    "recipe": (["recipe"], "HF"),
    "status": (["status"], "PHB"),
}
STATBLOCK_TAG_TYPES = {tag: types for tag, (types, _) in SIMPLE_TAG_DEFAULTS.items()}
STATBLOCK_TAG_TYPES.update({
    "class": ["class"], "subclass": ["subclass"], "deity": ["deity"],
    "classFeature": ["classFeature"], "subclassFeature": ["subclassFeature"], "card": ["card"],
})
REFERENCE_TAGS = set(SIMPLE_TAG_DEFAULTS) | {"class", "subclass", "classFeature", "subclassFeature", "deity", "card"}

EXCLUDED_TAG_NOTES = {
    "formatting/mechanical (dice rolls, bold/italic, skill/sense enums, filters, footnotes, ...)":
        sorted(["b", "i", "bold", "italic", "s", "strike", "u", "underline", "damage", "dc", "hit", "h", "atk",
                "dice", "skill", "filter", "sense", "recharge", "quickref", "note", "unit", "5etools",
                "scaledamage", "scaledice", "chance", "color", "link", "hom", "style", "m", "d20", "coinflip",
                "footnote", "hitYourSpellAttack"]),
    "navigational / out-of-taxonomy (point at book sections, adventures (not in our 51), or item-property codes, not one of our 36 entity types)":
        sorted(["book", "adventure", "itemProperty", "vehupgrade"]),
}

TAG_RE = re.compile(r"\{@(\w+)\s+([^{}]*)\}")
RACE_PAREN_RE = re.compile(r"^(.*?)\s*\(([^()]+)\)\s*$")
BONUS_PREFIX_RE = re.compile(r"^(?:[A-Za-z]+\s+)?[+-]\s*\d+\s+(.+)$")
ITEM_FAMILY = {"item", "baseitem", "magicvariant", "itemGroup"}


def _p(parts, i):
    return parts[i].strip() if i < len(parts) and parts[i].strip() != "" else None


def parse_tag(tag, argtext):
    parts = argtext.split("|")
    if tag in SIMPLE_TAG_DEFAULTS:
        types, default_src = SIMPLE_TAG_DEFAULTS[tag]
        name, source = _p(parts, 0), _p(parts, 1)
        return [{"type": t, "name": name, "source": source, "default_source": default_src, "extra": {}} for t in types]
    if tag == "class":
        return [{"type": "class", "name": _p(parts, 0), "source": _p(parts, 1), "default_source": "PHB", "extra": {}}]
    if tag == "subclass":
        className = _p(parts, 1)
        classSource = _p(parts, 2) or "PHB"
        source = _p(parts, 3)
        return [{"type": "subclass", "name": _p(parts, 0), "source": source, "default_source": classSource,
                 "extra": {"className": className}}]
    if tag == "classFeature":
        className = _p(parts, 1)
        classSource = _p(parts, 2) or "PHB"
        level = _p(parts, 3)
        source = _p(parts, 4)
        return [{"type": "classFeature", "name": _p(parts, 0), "source": source, "default_source": classSource,
                 "extra": {"className": className, "level": level}}]
    if tag == "subclassFeature":
        className = _p(parts, 1)
        classSource = _p(parts, 2) or "PHB"
        subclassShortName = _p(parts, 3)
        subclassSource = _p(parts, 4) or classSource
        level = _p(parts, 5)
        source = _p(parts, 6)
        return [{"type": "subclassFeature", "name": _p(parts, 0), "source": source, "default_source": subclassSource,
                 "extra": {"className": className, "subclassShortName": subclassShortName, "level": level}}]
    if tag == "deity":
        pantheon = _p(parts, 1) or "Forgotten Realms"
        source = _p(parts, 2)
        return [{"type": "deity", "name": _p(parts, 0), "source": source, "default_source": "PHB",
                 "extra": {"pantheon": pantheon}}]
    if tag == "card":
        set_ = _p(parts, 1)
        source = _p(parts, 2)
        return [{"type": "card", "name": _p(parts, 0), "source": source, "default_source": "DMG",
                 "extra": {"set": set_}}]
    return []


def statblock_to_refs(tag, name, source):
    types = STATBLOCK_TAG_TYPES.get(tag)
    if not types or not name:
        return None
    # statblock nodes always carry an explicit source -- reuse the ref-spec
    # shape with default_source==source so try_source() never needs a
    # separate "no source given" branch for these.
    return [{"type": t, "name": name, "source": source, "default_source": source, "extra": {}} for t in types]


def make_resolve_one(corpus_index, official_index):
    def resolve_one(ref):
        name = ref["name"]
        if not name:
            return None
        explicit_source = ref["source"] is not None
        extra = {k: v for k, v in ref["extra"].items() if v is not None}

        def try_source(src):
            if exists_in(corpus_index, ref["type"], name, src, extra):
                return "corpus"
            if exists_in(official_index, ref["type"], name, src, extra):
                return "official"
            if ref["type"] == "race":
                m = RACE_PAREN_RE.match(name)
                if m:
                    base, sub = m.group(1).strip(), m.group(2).strip()
                    if (exists_in(corpus_index, "race", base, src, {})
                            or exists_in(corpus_index, "subrace", sub, src, {"raceName": base})):
                        return "corpus"
                    if (exists_in(official_index, "race", base, src, {})
                            or exists_in(official_index, "subrace", sub, src, {"raceName": base})):
                        return "official"
            if ref["type"] in ITEM_FAMILY:
                # Generic magic-item variants (e.g. "+1 shield", "drow +2
                # studded leather armor") are resolved by the 5etools
                # renderer at render time by combining a bonus/material
                # prefix with a base item via requires/excludes filters on
                # the matching magicvariant -- we don't replicate that full
                # template engine, only the common "<prefix> +N <baseitem>"
                # shape, by checking the bare base item exists.
                m = BONUS_PREFIX_RE.match(name)
                if m:
                    base = m.group(1).strip()
                    if exists_in(corpus_index, "baseitem", base, src, {}) or exists_in(corpus_index, "item", base, src, {}):
                        return "corpus"
                    if exists_in(official_index, "baseitem", base, src, {}) or exists_in(official_index, "item", base, src, {}):
                        return "official"
            return None

        res = try_source(ref["source"] or ref["default_source"])
        if res:
            return res
        if not explicit_source:
            # Source was never given in the text at all (not merely empty in
            # a multi-pipe tag) -- our modelled default may not match 5etools'
            # real per-context default (e.g. deity pantheon-dependent
            # sources), so fall back to an any-source match before declaring
            # a dangling reference. An explicit-but-wrong source is never
            # retried this way: that's a genuine broken reference.
            res = try_source(None)
            if res:
                return res
        return "unresolved"

    return resolve_one


def path_to_str(path):
    out = []
    for p in path:
        if isinstance(p, int):
            out.append(f"[{p}]")
        else:
            out.append(("." if out else "") + str(p))
    return "".join(out)


def walk_and_collect(node, path, sink):
    if isinstance(node, dict):
        if node.get("type") == "statblock":
            sink.append(("statblock", node.get("tag"), node.get("name"), node.get("source"), tuple(path)))
        for k, v in node.items():
            path.append(k)
            walk_and_collect(v, path, sink)
            path.pop()
    elif isinstance(node, list):
        for i, v in enumerate(node):
            path.append(i)
            walk_and_collect(v, path, sink)
            path.pop()
    elif isinstance(node, str) and "{@" in node:
        for m in TAG_RE.finditer(node):
            tag, argtext = m.group(1), m.group(2)
            if tag in REFERENCE_TAGS:
                sink.append(("inline", tag, argtext, None, tuple(path)))


def collect_book_occurrences(merged):
    sink = []
    for type_name, val in merged.items():
        if type_name in ("_meta", "book"):
            continue
        walk_and_collect(val, [type_name], sink)
    return sink


def scan_references(all_merged, corpus_index, official_index):
    resolve_one = make_resolve_one(corpus_index, official_index)
    totals = Counter()
    unique_targets = {}
    order = {"corpus": 0, "official": 1, "unresolved": 2}

    for src, merged in all_merged.items():
        for kind, a, b, c, path in collect_book_occurrences(merged):
            if kind == "inline":
                tag, argtext = a, b
                refs = parse_tag(tag, argtext)
                display_tag = tag
            else:
                tag, name, source = a, b, c
                refs = statblock_to_refs(tag, name, source)
                display_tag = f"statblock:{tag}"

            if not refs:
                totals["malformed"] += 1
                continue

            display_name = refs[0]["name"]
            display_source = refs[0]["source"] or refs[0]["default_source"]
            bucket = "unresolved"
            for ref in refs:
                r = resolve_one(ref)
                if r == "corpus":
                    bucket = "corpus"
                    break
                if r == "official":
                    bucket = "official"
            totals[bucket] += 1

            canon_source = SOURCE_CANON.get(norm_source(display_source), display_source) if display_source else None
            key = (display_tag, norm_name(display_name), norm_source(display_source) if display_source else None)
            rec = unique_targets.get(key)
            if rec is None:
                rec = {"tag": display_tag, "name": display_name, "source": canon_source,
                       "bucket": bucket, "count": 0, "examples": []}
                unique_targets[key] = rec
            rec["count"] += 1
            if len(rec["examples"]) < 3:
                rec["examples"].append({"book": src, "location": path_to_str(path)})
            if order[bucket] < order[rec["bucket"]]:
                rec["bucket"] = bucket

    return totals, unique_targets


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    sources = [b["source"] for b in load_json(SOURCES_JSON)["books"]]

    official_index = build_official_index()

    all_merged, all_dup_log, all_combined_prov = {}, {}, {}
    for src in sources:
        merged, dup_log, combined_prov = merge_one_book(src)
        all_merged[src] = merged
        all_dup_log[src] = dup_log
        all_combined_prov[src] = combined_prov

    corpus_index = {}
    for merged in all_merged.values():
        for type_name, entities in merged.items():
            if type_name in ("_meta", "book", "bookData") or not isinstance(entities, list):
                continue
            add_records(corpus_index, type_name, entities)

    per_book_page_stats = {}
    all_miss_log = []
    for src in sources:
        stats = new_page_stats()
        restore_pages_for_book(official_index, all_merged[src], src, all_combined_prov[src], stats, all_miss_log)
        per_book_page_stats[src] = stats

    ref_totals, ref_unique_targets = scan_references(all_merged, corpus_index, official_index)

    # ---- write merged/<SOURCE>.json + merged/provenance/<SOURCE>.json ----
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    PROV_OUT_DIR.mkdir(parents=True, exist_ok=True)

    index_books = {}
    global_entity_counts = Counter()
    global_origin_counts = Counter()
    global_dups = 0
    global_page = new_page_stats()

    for src in sources:
        merged = all_merged[src]
        out_path = OUT_DIR / f"{src}.json"
        text = json.dumps(merged, indent="\t", ensure_ascii=False) + "\n"
        out_path.write_text(text, encoding="utf-8")

        prov_combined = all_combined_prov[src]
        prov_path = PROV_OUT_DIR / f"{src}.json"
        prov_path.write_text(json.dumps(prov_combined, indent="\t", ensure_ascii=False) + "\n", encoding="utf-8")

        entity_counts = {}
        origin_counts = Counter()
        for type_name, entities in merged.items():
            if type_name in ("_meta", "book", "bookData") or not isinstance(entities, list):
                continue
            entity_counts[type_name] = len(entities)
            global_entity_counts[type_name] += len(entities)
            group = TYPE_GROUP.get(type_name)
            prov_doc = prov_combined.get(group) if group else None
            for ent in entities:
                prov = get_provenance_record(group, prov_doc, type_name, ent)
                origin = prov.get("origin") if prov else "untracked"
                origin_counts[origin] += 1
                global_origin_counts[origin] += 1

        total_entities = sum(entity_counts.values())
        pstats = per_book_page_stats[src]
        for k in PAGE_STATS_KEYS:
            global_page[k] += pstats[k]
        total_misses = pstats["miss_no_record"] + pstats["miss_no_page_value"] + pstats["miss_ambiguous"] + pstats["miss_reprint_no_othersources"]

        book_meta = merged["book"][0] if merged.get("book") else {}
        index_books[src] = {
            "title": book_meta.get("name"),
            "entityCounts": entity_counts,
            "totalEntities": total_entities,
            "originCounts": dict(origin_counts),
            "duplicatesRemoved": len(all_dup_log[src]),
            "duplicates": all_dup_log[src],
            "pageRestoration": {
                "eligible": pstats["eligible"], "restored": pstats["restored"], "missing": total_misses,
            },
            "mergedFile": f"ref/5etools/merged/{src}.json",
            "mergedBytes": len(text.encode("utf-8")),
            "provenanceFile": f"ref/5etools/merged/provenance/{src}.json",
        }
        global_dups += len(all_dup_log[src])

    global_misses = (global_page["miss_no_record"] + global_page["miss_no_page_value"]
                     + global_page["miss_ambiguous"] + global_page["miss_reprint_no_othersources"])
    index_doc = {
        "generated": GEN_TIME,
        "sourceCount": len(sources),
        "totals": {
            "entityCount": sum(global_entity_counts.values()),
            "byType": dict(sorted(global_entity_counts.items())),
            "byOrigin": dict(global_origin_counts),
            "duplicatesRemoved": global_dups,
            "pageRestoration": {
                "eligible": global_page["eligible"],
                "restored": global_page["restored"],
                "missing": global_misses,
                "coveragePct": round(100 * global_page["restored"] / global_page["eligible"], 1) if global_page["eligible"] else None,
                "missBreakdown": {
                    "noOfficialRecord": global_page["miss_no_record"],
                    "officialRecordHasNoPageValue": global_page["miss_no_page_value"],
                    "ambiguousMultiplePages": global_page["miss_ambiguous"],
                    "reprintHasNoOtherSourcesEntryForThisBook": global_page["miss_reprint_no_othersources"],
                },
            },
        },
        "books": index_books,
    }
    (OUT_DIR / "_index.json").write_text(json.dumps(index_doc, indent="\t", ensure_ascii=False) + "\n", encoding="utf-8")

    # ---- _references.json ----
    corpus_targets = [v for v in ref_unique_targets.values() if v["bucket"] == "corpus"]
    official_targets = sorted((v for v in ref_unique_targets.values() if v["bucket"] == "official"), key=lambda v: -v["count"])
    unresolved_targets = sorted((v for v in ref_unique_targets.values() if v["bucket"] == "unresolved"), key=lambda v: -v["count"])
    corpus_occurrences = sum(v["count"] for v in corpus_targets)

    references_doc = {
        "generated": GEN_TIME,
        "methodology": {
            "scope": "Every {@tag ...} inline reference and every {type:'statblock', tag, name, source} node "
                     "found inside bookData and every merged entity array, for tags that reference one of our "
                     "36 extracted entity types. Resolution order: our 51-book merged corpus first, then "
                     "ref/5etools-src/data; text is never modified.",
            "includedTags": sorted(REFERENCE_TAGS),
            "excludedTagsReason": EXCLUDED_TAG_NOTES,
            "matching": "Case-insensitive on name and source. Disambiguating fields (className/level/"
                        "subclassShortName/raceName/set/pantheon) are matched when the tag supplies them.",
            "defaultSources": "Per-tag default source/pantheon when omitted from the tag text, taken from "
                               "ref/5etools-src/data/renderdemo.json's own documentation (e.g. '{@spell acid "
                               "splash} assumes PHB by default').",
            "lenientFallback": "If a tag omits its source entirely and the documented default doesn't resolve, "
                                "we retry with no source constraint at all before calling it unresolved (this "
                                "only ever loosens a *defaulted* source, never an explicitly-given one, so a "
                                "wrong explicit source is still reported as broken).",
            "knownLimitations": [
                "Generic magic-item variant names that combine a bonus/material prefix with a mundane base "
                "item (e.g. 'Arrow of Slaying (*)' + a creature type, material-prefixed armor) are resolved by "
                "the live 5etools renderer via its requires/excludes variant-template engine at render time, "
                "which this check does not reimplement; only the common '<prefix> +N <baseitem>' shape has a "
                "bounded fallback (strip the prefix, check the base item).",
                "A handful of 'statblock:creature' unresolved entries are wave-1 group/category headings (e.g. "
                "'Dinosaurs', 'Draconians') that were captured as a single creature-statblock placeholder "
                "instead of expanding to the individual creatures nested under that heading -- a markdown/wave-1 "
                "structural artifact, not a reference-resolution bug.",
            ],
        },
        "summary": {
            "occurrencesScanned": sum(ref_totals.values()),
            "malformedSkipped": ref_totals.get("malformed", 0),
            "resolvedInCorpus": ref_totals.get("corpus", 0),
            "resolvedOnlyInOfficialData": ref_totals.get("official", 0),
            "unresolved": ref_totals.get("unresolved", 0),
            "uniqueTargets": {
                "resolvedInCorpus": len(corpus_targets),
                "resolvedOnlyInOfficialData": len(official_targets),
                "unresolved": len(unresolved_targets),
            },
        },
        "resolvedInCorpus": {
            "occurrences": corpus_occurrences,
            "uniqueTargets": len(corpus_targets),
            "note": "Full per-occurrence detail omitted (not actionable); top targets by occurrence count shown "
                    "for spot-checking.",
            "sample": sorted(corpus_targets, key=lambda v: -v["count"])[:10],
        },
        "resolvedOnlyInOfficialData": official_targets,
        "unresolved": unresolved_targets,
    }
    (OUT_DIR / "_references.json").write_text(json.dumps(references_doc, indent="\t", ensure_ascii=False) + "\n", encoding="utf-8")

    # ---- console report ----
    print(f"Merged {len(sources)} books -> {OUT_DIR}")
    print(f"Total entities: {sum(global_entity_counts.values())}  duplicatesRemoved: {global_dups}")
    print(f"Page restoration: eligible={global_page['eligible']} restored={global_page['restored']} "
          f"missing={global_misses} coverage={index_doc['totals']['pageRestoration']['coveragePct']}%")
    print(f"References: scanned={sum(ref_totals.values())} corpus={ref_totals.get('corpus',0)} "
          f"official={ref_totals.get('official',0)} unresolved={ref_totals.get('unresolved',0)}")
    print(f"Unique unresolved targets: {len(unresolved_targets)}; top examples:")
    for v in unresolved_targets[:15]:
        print(f"  x{v['count']:<4d} {v['tag']:16s} {v['name']!r} (source={v['source']!r}) -> {v['examples'][0]}")


if __name__ == "__main__":
    main()
