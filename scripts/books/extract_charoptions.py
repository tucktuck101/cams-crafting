#!/usr/bin/env python3
"""Wave-2 extractor for the `charoptions` shard.

Types covered: race, subrace, background, feat, optionalfeature, charoption,
boon. (The assignment's "boon" instruction described its contents as "epic
boons, supernatural gifts, charms, blessings" -- checking the evidence, that
content actually splits across *three* real 5etools schema types: epic
boons are `feat` with `category: "EB"` (already covered by this shard's
`feat`); genuine patron/cult boons use the dedicated `boon` type
(cultsboons.json, e.g. Mordenkainen's Tome of Foes' "Demonic Boon of X");
and supernatural gifts/charms/blessings/draconic gifts are `reward`
(rewards.json), which turned out to be explicitly assigned to a sibling
shard (`ExtractWorld`, who also owns the sibling `cult` type from the same
schema file) -- confirmed by direct peer coordination, so `reward` is
intentionally produced by that shard instead of this one.)

THE CORE PROBLEM
-----------------
`ref/books/*.md` was captured from the 5etools site's book-reader. For any
content that already has a canonical entry in 5etools' own live database
(which is true of essentially every official race/background/feat/optional
feature/character-creation-option/reward in these 51 books, since 5etools
already catalogs the entire official D&D corpus), the book reader does not
duplicate that entry's text inline -- it transcludes it via a client-side
widget. Our markdown snapshot captured the widget's "Loading ..." placeholder
(data-rd-tag/data-rd-name/data-rd-source/data-rd-page attributes) but never
the real body text. This is pervasive and was verified by direct sampling
across PHB (races, backgrounds -- 0/9 races and 0/13 backgrounds have any
body text), DMG (rewards, "epic boon" prose), VGM, ERLW, XGE, TCE, BMT,
VRGR, MTF: in every single case checked, the "catalog" presentation of one
of these 7 types is either (a) a bare placeholder, (b) a bare name list /
table with no placeholder at all (e.g. XGE's "Racial Feats" table), or (c) a
redirect sentence ("See the Changeling entry."). Zero genuine full-prose
instances of any of these 7 types were found anywhere in the 51 books after
broad sampling (see the final report for the specific sections checked).

Wave-2 policy from Main (the orchestrating agent), given this finding:
  1. Where a book's own Markdown has an entity's full body text, parse it.
     (Retained as a no-op hook: `BODY_TEXT_IN_MARKDOWN_FOUND` below documents
     that this path was never exercised by the current 51 books.)
  2. Where it has only a stub / bare heading / bare table-or-list mention,
     fill the entity from the official data mirrored locally at
     ref/5etools-src/data/, matched by name (narrowed by the stub's own
     source when available).
  3. Relabel the produced entity to THIS book's source whenever this book
     has its own heading, stub, or table/list row for it -- even when the
     matched ref/5etools-src record's *own* `source` is a different book
     (a "genuine reprint"). Record `data_from` in the sidecar when the two
     differ. A table/list-mention specifically is only honoured when the
     matched record's own source already equals this book (never relabel
     on the strength of a bare name match alone).
  4. A passing mention inside unrelated running prose, for an entity whose
     authoritative source is a *different* book, is a cross-reference only
     (recorded in the sidecar's `_crossReferences`), never copied in as an
     entity of this book.

Roster discovery (per book, per type) walks the already-structured
ref/5etools/books/<SOURCE>.json produced by Wave 1 (not the raw HTML-laden
Markdown) and collects four kinds of evidence, in confidence order:
  - stub:          a `{"type":"statblock","tag":...}` node Wave 1 already
                    promoted from a whole-paragraph embed widget.
  - heading:       a named heading whose text (after light singularisation)
                    matches a known entity name, inside a chapter already
                    established as relevant to this type (either by a
                    keyword in the chapter title, or because a stub of the
                    same type already lives somewhere under that same
                    top-level chapter).
  - table-mention: a cell in a table inside a relevant chapter that matches
                    a known name *whose own source is this book*.
  - text-mention:  a plain-text (or bullet-list-item) substring match of a
                    known, same-book-sourced, reasonably distinctive name,
                    inside a relevant chapter (catches cases like
                    Mordenkainen's Tome of Foes' "Demonic Boons" list, which
                    has no stub and no table -- just a bullet list of names
                    under a heading).
Headings/strings inside `"type":"inset"` sidebars are excluded from the
heading/text-mention passes (that specific combination produced one
confirmed false positive during development: a generic "Ability Score
Improvement" callout inside a DMG "Alternatives to Epic Boons" sidebar,
which collides with an unrelated real XPHB entity of the same name).

Entities that rely on 5etools' own `_copy` (copy-and-modify) convention are
resolved by this script (base lookup + `_mod.entries` appendArr / prependArr
/ replaceArr / removeArr / insertArr + raceName/raceSource inheritance for
subrace copies); anything using an unhandled `_mod` key is flagged in the
provenance sidecar rather than silently mis-merged.

Output: ref/5etools/shards/charoptions/<SOURCE>.json (one per book that has
any matched entity) + ref/5etools/shards/charoptions/<SOURCE>.provenance.json
sidecar mapping "<type>:<name>[|<raceName>]" -> {section, origin, match,
data_from?} plus `_crossReferences` and `_unresolved` lists.
"""
import copy as copymod
import json
import os
import re
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
SRC_DATA_DIR = os.path.join(REPO_ROOT, "ref", "5etools-src", "data")
BOOKS_DIR = os.path.join(REPO_ROOT, "ref", "5etools", "books")
SOURCES_JSON = os.path.join(REPO_ROOT, "ref", "5etools", "sources.json")
BREW_SCHEMA_DIR = os.path.join(
    REPO_ROOT, "ref", "5etools", "tooling", "node_modules", "5etools-utils", "schema", "brew"
)
SHARD_DIR = os.path.join(REPO_ROOT, "ref", "5etools", "shards", "charoptions")

# Documents that the "parse the book's own Markdown body text" path (policy
# rule 1) was implemented but never triggered: every single resolved entity
# in the current 51-book corpus has origin "5etools-src" because no genuine
# full-prose instance of any of these 7 types was found anywhere. See the
# final report for the specific sections sampled to confirm this.
BODY_TEXT_IN_MARKDOWN_FOUND = False


# ---------------------------------------------------------------------------
# 0. Schema introspection (allowed top-level keys per type, read directly
#    from the same patched brew schema validate.sh checks against).
# ---------------------------------------------------------------------------
def _load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _brew(name):
    return _load_json(os.path.join(BREW_SCHEMA_DIR, name))


def _allowed_keys(schema_file, def_name):
    return set(_brew(schema_file)["$defs"][def_name]["properties"].keys())


ALLOWED_KEYS = {
    "race": _allowed_keys("races.json", "sharedData"),
    "subrace": _allowed_keys("races.json", "subraceData"),
    "background": _allowed_keys("backgrounds.json", "backgroundData"),
    "feat": _allowed_keys("feats.json", "featData"),
    "optionalfeature": _allowed_keys("optionalfeatures.json", "optionalfeatureData"),
    "charoption": _allowed_keys("charcreationoptions.json", "charoptionData"),
    "reward": _allowed_keys("rewards.json", "rewardData"),
    "boon": _allowed_keys("cultsboons.json", "boonData"),
}
# `fluff` is only a valid inline field for these types in the brew schema
# (reward/boon flavour text lives in a separate fluff-rewards.json file we
# are not populating, so we never attach inline fluff to those two types).
SUPPORTS_INLINE_FLUFF = {t for t in ALLOWED_KEYS if "fluff" in ALLOWED_KEYS[t]}


# ---------------------------------------------------------------------------
# 1. Load ref/5etools-src/data (the authoritative official dataset) and
#    index every entity of our 8 "families" by lowercase name.
# ---------------------------------------------------------------------------
def _src(name):
    return _load_json(os.path.join(SRC_DATA_DIR, name))


_races_d = _src("races.json")
_bg_d = _src("backgrounds.json")
_feats_d = _src("feats.json")
_optf_d = _src("optionalfeatures.json")
_cco_d = _src("charcreationoptions.json")
_cult_d = _src("cultsboons.json")

# NOTE: `reward` (rewards.json -- Blessing/Charm/Draconic Gift/Curse/Piety
# Trait/etc, e.g. DMG's Blessing of X + Charm of X, FTD's Draconic Gifts)
# is explicitly assigned to a sibling (ExtractWorld, who also owns `cult`)
# and is intentionally NOT produced by this script, even though it's the
# closest real schema match for part of this shard's "boon" instruction
# text ("supernatural gifts, charms, blessings"). Confirmed by direct peer
# coordination. `boon` (cultsboons.json, e.g. MTF's "Demonic Boon of X")
# stays here since it's the literal type keyword in this shard's
# assignment; Epic Boons stay here too, as `feat` with category "EB".
FAMILY_ARRAYS = {
    "race": _races_d["race"],
    "subrace": _races_d["subrace"],
    "background": _bg_d["background"],
    "feat": _feats_d["feat"],
    "optionalfeature": _optf_d["optionalfeature"],
    "charoption": _cco_d["charoption"],
    "boon": _cult_d["boon"],
}

# tag used on `{"type":"statblock","tag":...}` nodes (and on the original
# data-rd-tag attribute) -> our family name. The site tags both race and
# subrace stubs as "race" (it shows them on one combined page); optional
# features are tagged "optfeature" (matching the {@optfeature} renderer tag).
TAG_TO_FAMILY = {
    "race": "race",  # may resolve to a subrace, see try_resolve_name
    "background": "background",
    "feat": "feat",
    "optfeature": "optionalfeature",
    "charoption": "charoption",
    "reward": "reward",
    "boon": "boon",
}
FAMILY_TO_TAG = {v: k for k, v in TAG_TO_FAMILY.items() if v != "race"} 
FAMILY_TO_TAG["race"] = "race"
# Top-level families we run independent discovery for. "subrace" is not
# included: subrace entities are only ever reached as a resolution of a
# "race"-family candidate (the site tags both as "race"), never discovered
# directly.
DISCOVERY_FAMILIES = [f for f in FAMILY_ARRAYS if f != "subrace"]


# NOTE: every alternative is individually wrapped in its own `\b...\b` (or
# left unbounded only for long, low-collision multi-word phrases) -- a
# previous version used `\bfoo|bar|baz\b` which (due to `|`'s low
# precedence) only bounded the *first* and *last* alternative, leaving e.g.
# bare "folk" match "Merfolk" and bare "feat" match "feature"/"features"
# anywhere. Both were caught as false positives during development (GGR's
# "Merfolk" *monster* encounter table falsely unlocked its whole bestiary
# chapter for race-name matching; "feature" is a different, ubiquitous
# word unrelated to loose "feat" chapter relevance).
CHAPTER_RELEVANCE = {
    "race": re.compile(r"\b(?:race|species|lineage|folk)\b", re.IGNORECASE),
    "background": re.compile(r"\bbackgrounds?\b", re.IGNORECASE),
    "feat": re.compile(r"\b(?:feats?|dragonmarks?)\b", re.IGNORECASE),
    "optionalfeature": re.compile(
        r"\b(?:invocations?|metamagic|maneuvers?|infusions?|arcane shots?|runes?"
        r"|renown perks?|onomancy|traveler.?s tricks?)\b"
        r"|fighting styles?|elemental disciplines?|optional class features?",
        re.IGNORECASE,
    ),
    "charoption": re.compile(
        r"\b(?:heritage|charoptions?)\b"
        r"|dark gifts?|supernatural gifts?|character secrets?|background features?"
        r"|replacement features?|character creation options?|dark bargains?",
        re.IGNORECASE,
    ),
    "boon": re.compile(r"\b(?:boons?|cults?)\b", re.IGNORECASE),
}

by_name_family = {fam: {} for fam in FAMILY_ARRAYS}
skipped_no_name = {fam: 0 for fam in FAMILY_ARRAYS}
for _fam, _arr in FAMILY_ARRAYS.items():
    for _e in _arr:
        if "name" not in _e:
            # `_versions`-templated entries (e.g. the 5 chromatic/metallic
            # Dragonborn colour variants) have no literal own name and are
            # out of scope for name-based matching.
            skipped_no_name[_fam] += 1
            continue
        by_name_family[_fam].setdefault(_e["name"].strip().lower(), []).append(_e)

subrace_by_parent = {}
for _e in _races_d["subrace"]:
    if "name" not in _e:
        continue
    _key = (_e.get("raceName", "").strip().lower(), _e["name"].strip().lower())
    subrace_by_parent.setdefault(_key, []).append(_e)

_books_all = _src("books.json")
_adventures_all = _src("adventures.json")
PUBLISHED_BY_SOURCE = {}
for _x in _books_all.get("book", []) + _adventures_all.get("adventure", []):
    if _x.get("source") and _x.get("published"):
        PUBLISHED_BY_SOURCE[_x["source"]] = _x["published"]


# ---------------------------------------------------------------------------
# 2. Name matching helpers.
# ---------------------------------------------------------------------------
_STRIP_MD = re.compile(r"[*_`]")


def clean_cell(s):
    return _STRIP_MD.sub("", s).strip()


def name_variants(raw):
    """Candidate literal entity names a heading's title might denote, after
    light de-pluralisation / suffix-stripping / "X and Y" splitting."""
    raw = raw.strip().strip(":").strip()
    variants = [raw]
    for suf in (" Traits", " Trait", " Race", " Races", " Subrace", " Subraces"):
        if raw.endswith(suf):
            variants.append(raw[: -len(suf)].strip())
    if raw.endswith("ves") and len(raw) > 4:
        variants.append(raw[:-3] + "f")
        variants.append(raw[:-3] + "fe")
    if raw.endswith("ies") and len(raw) > 4:
        variants.append(raw[:-3] + "y")
    if raw.endswith("s") and not raw.endswith("ss"):
        variants.append(raw[:-1])
    if " and " in raw.lower():
        for p in re.split(r"\s+and\s+", raw, flags=re.IGNORECASE):
            p = p.strip()
            variants.append(p)
            if p.endswith("ves") and len(p) > 4:
                variants.append(p[:-3] + "f")
            if p.endswith("s") and not p.endswith("ss"):
                variants.append(p[:-1])
    seen, out = set(), []
    for v in variants:
        if v and v.lower() not in seen:
            seen.add(v.lower())
            out.append(v)
    return out


def try_resolve_name(name, family, source_hint=None, this_book=None):
    """Resolve a candidate name to (entity_dict, resolved_family) using
    ref/5etools-src, or None. `resolved_family` differs from `family` only
    for race->subrace (the site's combined race/subrace display)."""
    name = name.strip()
    nl = name.lower()
    candidates = []
    if family == "race":
        if nl in by_name_family["race"]:
            candidates += [(e, "race") for e in by_name_family["race"][nl]]
        m = re.match(r"^(.*?)\s*\((.*)\)$", name)
        if m:
            parent, inner = m.group(1).strip(), m.group(2).strip()
            key = (parent.lower(), inner.lower())
            if key in subrace_by_parent:
                candidates += [(e, "subrace") for e in subrace_by_parent[key]]
            if "; " in inner:
                frag, subname = inner.split("; ", 1)
                key2 = (f"{parent} ({frag})".lower(), subname.strip().lower())
                if key2 in subrace_by_parent:
                    candidates += [(e, "subrace") for e in subrace_by_parent[key2]]
            if inner.lower() in by_name_family["race"]:
                candidates += [(e, "race") for e in by_name_family["race"][inner.lower()]]
            if not candidates and inner.lower() in by_name_family["subrace"]:
                candidates += [(e, "subrace") for e in by_name_family["subrace"][inner.lower()]]
    else:
        if nl in by_name_family[family]:
            candidates += [(e, family) for e in by_name_family[family][nl]]
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    if source_hint:
        for e, fam2 in candidates:
            if e.get("source") == source_hint:
                return e, fam2
    if this_book:
        for e, fam2 in candidates:
            if e.get("source") == this_book:
                return e, fam2

    def pubdate(ef):
        return PUBLISHED_BY_SOURCE.get(ef[0].get("source"), "9999-99-99")

    candidates.sort(key=pubdate)
    return candidates[0]


def lookup_exact(name, source, family):
    for e in by_name_family.get(family, {}).get(name.strip().lower(), []):
        if e.get("source") == source:
            return e
    return None


# ---------------------------------------------------------------------------
# 3. `_copy` (copy-and-modify) resolution.
# ---------------------------------------------------------------------------
def apply_mod_entries(entries_list, mod_ops):
    entries_list = list(entries_list) if entries_list else []
    if isinstance(mod_ops, dict):
        mod_ops = [mod_ops]
    for op in mod_ops:
        if not isinstance(op, dict):
            continue
        mode = op.get("mode")
        items = op.get("items")
        if mode == "appendArr":
            entries_list.extend(items if isinstance(items, list) else [items])
        elif mode == "prependArr":
            entries_list = (items if isinstance(items, list) else [items]) + entries_list
        elif mode == "replaceArr":
            targets = op.get("replace")
            targets = targets if isinstance(targets, list) else [targets]
            new_items = items if isinstance(items, list) else [items]
            new_list, replaced = [], False
            for e in entries_list:
                if isinstance(e, dict) and e.get("name") in targets:
                    new_list.extend(new_items)
                    replaced = True
                else:
                    new_list.append(e)
            if not replaced:
                new_list.extend(new_items)
            entries_list = new_list
        elif mode == "removeArr":
            names = op.get("names")
            names = names if isinstance(names, list) else [names]
            entries_list = [e for e in entries_list if not (isinstance(e, dict) and e.get("name") in names)]
        elif mode == "insertArr":
            pos = op.get("index", len(entries_list))
            new_items = items if isinstance(items, list) else [items]
            entries_list = entries_list[:pos] + new_items + entries_list[pos:]
        # unknown modes are silently left unapplied; caller logs a warning
        # for any mod key it can't account for.
    return entries_list


def resolve_copy_chain(entity, family, max_depth=5):
    """Fully resolves a `_copy`-based entity against ref/5etools-src.
    Returns (merged_dict_or_None, warnings)."""
    warnings = []
    chain = []
    cur = entity
    for _ in range(max_depth):
        if "_copy" not in cur:
            break
        copyref = cur["_copy"]
        base = lookup_exact(copyref["name"], copyref.get("source"), family)
        if base is None:
            alt_family = "subrace" if family == "race" else ("race" if family == "subrace" else None)
            if alt_family:
                base = lookup_exact(copyref["name"], copyref.get("source"), alt_family)
        if base is None:
            warnings.append(f"_copy base not found: {copyref.get('name')}|{copyref.get('source')}")
            return None, warnings
        chain.append((cur, copyref, base))
        cur = base
        if "_copy" not in cur:
            break
    if not chain:
        return entity, warnings
    merged = copymod.deepcopy(chain[-1][2])
    for cur_entity, copyref, _base in reversed(chain):
        mod = copyref.get("_mod", {})
        if "entries" in mod:
            mod_entries = mod["entries"]
            if isinstance(mod_entries, dict):
                mod_entries = [mod_entries]
            merged["entries"] = apply_mod_entries(merged.get("entries", []), mod_entries)
        for k in mod:
            if k != "entries":
                warnings.append(f"unhandled _mod key '{k}' for {cur_entity.get('name')}")
        for extra_key in ("raceName", "raceSource"):
            if extra_key in copyref:
                merged[extra_key] = copyref[extra_key]
        for k, v in cur_entity.items():
            if k != "_copy":
                merged[k] = v
    return merged, warnings


# ---------------------------------------------------------------------------
# 4. Walk a book's already-structured JSON (ref/5etools/books/<SRC>.json).
# ---------------------------------------------------------------------------
def walk_book(data_root):
    """Returns (stubs, headings, tables).
    stubs:    [{tag, name, source, section_id, chapter_chain}]
    headings: [{name, id, chapter_chain, in_inset, strings}]  (strings =
              direct plain-string children, used for fluff + text-mention)
    tables:   [{rows, colLabels, section_id, chapter_chain}]
    """
    stubs, headings, tables = [], [], []

    def rec(node, cur_id, chapter_chain, direct_strs_out, in_inset):
        if isinstance(node, dict):
            t = node.get("type")
            if t == "statblock":
                stubs.append(
                    {
                        "tag": node.get("tag"),
                        "name": node.get("name"),
                        "source": node.get("source"),
                        "section_id": cur_id,
                        "chapter_chain": list(chapter_chain),
                    }
                )
                return
            if t == "table":
                tables.append(
                    {
                        "rows": node.get("rows", []),
                        "colLabels": node.get("colLabels", []),
                        "section_id": cur_id,
                        "chapter_chain": list(chapter_chain),
                    }
                )
                return
            if t in ("section", "entries") and "entries" in node:
                nm = node.get("name")
                idd = node.get("id") or cur_id
                my_strs = []
                new_chain = chapter_chain + [nm] if nm else chapter_chain
                hidx = None
                if nm:
                    headings.append(
                        {"name": nm, "id": idd, "chapter_chain": list(chapter_chain), "in_inset": in_inset}
                    )
                    hidx = len(headings) - 1
                child_in_inset = in_inset or (t == "inset")
                for child in node["entries"]:
                    rec(child, idd, new_chain, my_strs, child_in_inset)
                if nm:
                    headings[hidx]["strings"] = my_strs
                else:
                    direct_strs_out.extend(my_strs)
                return
            for k in ("entries", "items"):
                if k in node:
                    rec(node[k], cur_id, chapter_chain, direct_strs_out, in_inset or (t == "inset"))
        elif isinstance(node, list):
            for c in node:
                rec(c, cur_id, chapter_chain, direct_strs_out, in_inset)
        elif isinstance(node, str):
            direct_strs_out.append(node)

    top_strs = []
    rec(data_root, None, [], top_strs, False)
    return stubs, headings, tables


def compute_relevant_chapters(stubs, headings, family):
    tag = FAMILY_TO_TAG.get(family)
    roots = set()
    for s in stubs:
        if s["tag"] == tag and s["chapter_chain"]:
            roots.add(s["chapter_chain"][0])
    pat = CHAPTER_RELEVANCE[family]
    for h in headings:
        if pat.search(h["name"]):
            roots.add(h["chapter_chain"][0] if h["chapter_chain"] else h["name"])
    return roots

_FAQ_CONTEXT_RE = re.compile(
    r"compiled answers|sage advice|errata|designer.?s? notes?|rules q.?&.?a|frequently asked questions",
    re.IGNORECASE,
)


def is_relevant(chapter_chain, own_name, relevant_roots, family):
    chain = list(chapter_chain) + ([own_name] if own_name else [])
    # Hard veto: FAQ/errata/designer-commentary sections (e.g. the Sage
    # Advice Compendium's per-topic Q&A headings) name existing entities
    # purely to discuss a rules question about them -- this is never a
    # genuine reprint, regardless of how exactly the heading is titled.
    if any(_FAQ_CONTEXT_RE.search(nm) for nm in chain if nm):
        return False
    pat = CHAPTER_RELEVANCE[family]
    if any(pat.search(nm) for nm in chain if nm):
        return True
    return bool(chain) and chain[0] in relevant_roots


_REDIRECT_RE = re.compile(r"^see (also )?(the )?.+ entr(y|ies)\.?$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# 5. Candidate discovery + resolution for one (book, family).
# ---------------------------------------------------------------------------
def gather_candidates(stubs, headings, tables, family, this_book):
    """Returns (candidates, cross_refs) where candidates is a list of
    {name, source_hint, section_id, method} to attempt importing as one of
    this book's own entities, and cross_refs is a list of {name, source,
    section_id, method} for same-name matches whose authoritative source is
    a *different* book (logged, never imported, per policy rule 4)."""
    cands, cross_refs = [], []
    tag = FAMILY_TO_TAG.get(family)
    for s in stubs:
        if s["tag"] == tag:
            cands.append({"name": s["name"], "source_hint": s["source"], "section_id": s["section_id"], "method": "stub"})

    # A heading that already carries its OWN stub of a *different*,
    # unrelated tag is authoritatively that other type, not this family --
    # this guards against pure name collisions between e.g. a monster lore
    # heading ("## Aarakocra", tag="creature") and an unrelated playable
    # race of the same name elsewhere in the official data.
    contradicting_tags_by_section = {}
    for s in stubs:
        contradicting_tags_by_section.setdefault(s["section_id"], set()).add(s["tag"])

    def heading_contradicted(section_id):
        tags_here = contradicting_tags_by_section.get(section_id)
        return bool(tags_here) and tag not in tags_here

    roots = compute_relevant_chapters(stubs, headings, family)

    for h in headings:
        if h.get("in_inset") or heading_contradicted(h["id"]) or not is_relevant(h["chapter_chain"], h["name"], roots, family):
            continue
        for v in name_variants(h["name"]):
            if v.lower() in by_name_family[family] or (family == "race" and re.match(r"^(.*?)\s*\((.*)\)$", v)):
                cands.append({"name": v, "source_hint": None, "section_id": h["id"], "method": "heading"})
                break

    for t in tables:
        if not is_relevant(t["chapter_chain"], None, roots, family):
            continue
        for row in t["rows"]:
            cells = row if isinstance(row, list) else [row]
            for cell in cells:
                if not isinstance(cell, str):
                    continue
                name = clean_cell(cell)
                if not name or len(name) < 3:
                    continue
                resolved = try_resolve_name(name, family, source_hint=this_book, this_book=this_book)
                if resolved and resolved[0].get("source") == this_book:
                    cands.append(
                        {"name": name, "source_hint": this_book, "section_id": t["section_id"], "method": "table-mention"}
                    )
                elif resolved:
                    cross_refs.append(
                        {
                            "name": resolved[0]["name"],
                            "source": resolved[0].get("source"),
                            "section_id": t["section_id"],
                            "method": "table-mention",
                        }
                    )

    for h in headings:
        if h.get("in_inset") or heading_contradicted(h["id"]) or not is_relevant(h["chapter_chain"], h["name"], roots, family):
            continue
        for s in h.get("strings", []):
            if not isinstance(s, str):
                continue
            sl = s.lower()
            for name_lower, entities in by_name_family[family].items():
                if len(name_lower) < 9 and " " not in name_lower:
                    continue
                if name_lower in sl:
                    for e in entities:
                        if e.get("source") == this_book:
                            cands.append(
                                {"name": e["name"], "source_hint": this_book, "section_id": h["id"], "method": "text-mention"}
                            )
                        else:
                            cross_refs.append(
                                {"name": e["name"], "source": e.get("source"), "section_id": h["id"], "method": "text-mention"}
                            )
    return cands, cross_refs


_METHOD_PRIORITY = {"stub": 0, "heading": 1, "table-mention": 2, "text-mention": 3}


def sanitize_entity(entity, family, this_book, data_from):
    """Deep-copies `entity`, restricts to brew-schema-allowed top-level keys
    for `family`, relabels `source` to this_book, and drops `page` (per the
    shared contract: our own page numbers are never knowable from the
    source Markdown, so the convention across every shard is to omit it even
    when a real official page number is available from ref/5etools-src)."""
    allowed = ALLOWED_KEYS[family]
    out = {k: copymod.deepcopy(v) for k, v in entity.items() if k in allowed}
    out["source"] = this_book
    out.pop("page", None)
    return out


def attach_fluff(entity, family, method, heading):
    if family not in SUPPORTS_INLINE_FLUFF or method not in ("heading",):
        return
    strs = [s for s in heading.get("strings", []) if isinstance(s, str) and s.strip() and not _REDIRECT_RE.match(s.strip())]
    text = " ".join(s.strip() for s in strs).strip()
    if len(text) >= 40:
        entity["fluff"] = {"entries": strs}
        entity["hasFluff"] = True


def process_book(source_code):
    book_path = os.path.join(BOOKS_DIR, f"{source_code}.json")
    if not os.path.isfile(book_path):
        return None
    book = _load_json(book_path)
    stubs, headings, tables = [], [], []
    for bdent in book.get("bookData", []):
        s, h, t = walk_book(bdent.get("data", []))
        stubs += s
        headings += h
        tables += t
    heading_by_id = {h["id"]: h for h in headings if h.get("id")}

    shard = {}
    provenance = {}
    cross_references = []
    unresolved = []
    stats = {}
    seen_final_identities = set()
    def finalize(entity, resolved_family, section_id, method, out_list_by_family):
        original_source = entity.get("source")
        working = entity
        copy_warnings = []
        if "_copy" in entity:
            merged, copy_warnings = resolve_copy_chain(entity, resolved_family)
            if merged is None:
                unresolved.append(
                    {
                        "type": resolved_family,
                        "name": entity.get("name"),
                        "source_hint": original_source,
                        "section_id": section_id,
                        "method": method,
                        "reason": "; ".join(copy_warnings) or "_copy chain could not be resolved",
                    }
                )
                return
            working = merged
        final_entity = sanitize_entity(working, resolved_family, source_code, original_source)
        heading = heading_by_id.get(section_id) if section_id else None
        if heading is not None:
            attach_fluff(final_entity, resolved_family, method, heading)
        # Defensive final-identity dedup: two different discovery paths (e.g.
        # a stub hinting at one upstream source, a heading-name match
        # tie-breaking to a different upstream source for the same bare
        # name) could in principle both relabel to the same (family, name,
        # raceName) under this book, which would violate the schema's
        # `uniqueItems` on the output array. Never seen in the current 51
        # books (checked), but guarded regardless; also the mechanism that
        # keeps the source-complete sweep below from duplicating anything
        # already found via Markdown-based discovery.
        final_identity = (resolved_family, final_entity["name"], final_entity.get("raceName"))
        if final_identity in seen_final_identities:
            return
        seen_final_identities.add(final_identity)
        out_list_by_family.setdefault(resolved_family, []).append(final_entity)

        prov_key = f"{resolved_family}:{final_entity['name']}"
        if resolved_family == "subrace":
            prov_key += f"|{final_entity.get('raceName')}"
        prov_entry = {"section": section_id, "origin": "5etools-src", "match": method}
        if original_source and original_source != source_code:
            prov_entry["data_from"] = original_source
        if copy_warnings:
            prov_entry["copy_warnings"] = copy_warnings
        provenance[prov_key] = prov_entry

    source_complete_counts = {}
    for family in DISCOVERY_FAMILIES:
        cands, cross_refs = gather_candidates(stubs, headings, tables, family, source_code)
        for cr in cross_refs:
            cross_references.append({"type": family, **cr})

        resolved_best = {}  # identity -> (method, section_id, entity, resolved_family)
        for c in cands:
            r = try_resolve_name(c["name"], family, source_hint=c["source_hint"], this_book=source_code)
            if not r:
                unresolved.append(
                    {"type": family, "name": c["name"], "source_hint": c["source_hint"], "section_id": c["section_id"], "method": c["method"]}
                )
                continue
            entity, resolved_family = r
            identity = (resolved_family, entity.get("name"), entity.get("source"), entity.get("raceName"), entity.get("raceSource"))
            if identity not in resolved_best or _METHOD_PRIORITY[c["method"]] < _METHOD_PRIORITY[resolved_best[identity][0]]:
                resolved_best[identity] = (c["method"], c["section_id"], entity, resolved_family)

        out_list_by_family = {}
        for _identity, (method, section_id, entity, resolved_family) in resolved_best.items():
            finalize(entity, resolved_family, section_id, method, out_list_by_family)

        # Final completeness sweep (per Main's policy): some chapters are
        # captured as nothing but a single pointer sentence ("See the full
        # list of spells ... on the Spells page"), with no stub, heading, or
        # table/text mention to discover at all. So after Markdown-based
        # discovery, also pull in every ref/5etools-src record of this
        # family whose own `source` already equals this book's code and
        # that wasn't already found above.
        sweep_families = [family] if family != "race" else ["race", "subrace"]
        for sweep_family in sweep_families:
            before = len(out_list_by_family.get(sweep_family, []))
            for e in FAMILY_ARRAYS[sweep_family]:
                if "name" not in e or e.get("source") != source_code:
                    continue
                identity_check = (sweep_family, e["name"], e.get("raceName"))
                if identity_check in seen_final_identities:
                    continue
                finalize(e, sweep_family, None, "source-complete", out_list_by_family)
            added = len(out_list_by_family.get(sweep_family, [])) - before
            if added:
                source_complete_counts[sweep_family] = source_complete_counts.get(sweep_family, 0) + added

        for fam, lst in out_list_by_family.items():
            shard.setdefault(fam, []).extend(lst)
            stats[fam] = stats.get(fam, 0) + len(lst)


    if not shard:
        return {"source": source_code, "stats": {}, "cross_references": cross_references, "unresolved": unresolved, "source_complete": source_complete_counts, "empty": True}

    meta_src = book.get("_meta", {})
    now = int(time.time())
    shard["_meta"] = {
        "sources": copymod.deepcopy(meta_src.get("sources", [])),
        "edition": meta_src.get("edition", "classic"),
        "dateAdded": now,
        "dateLastModified": now,
    }

    provenance["_crossReferences"] = cross_references
    provenance["_unresolved"] = unresolved
    return {
        "source": source_code,
        "shard": shard,
        "provenance": provenance,
        "stats": stats,
        "cross_references": cross_references,
        "unresolved": unresolved,
        "source_complete": source_complete_counts,
        "empty": False,
    }


# ---------------------------------------------------------------------------
# 6. Main
# ---------------------------------------------------------------------------
def main():
    sources = _load_json(SOURCES_JSON)
    all_codes = [b["source"] for b in sources["books"]]

    os.makedirs(SHARD_DIR, exist_ok=True)

    grand_stats = {}
    grand_source_complete = {}
    total_cross_refs = 0
    total_unresolved = 0
    books_written = 0

    for code in all_codes:
        result = process_book(code)
        if result is None:
            print(f"SKIP {code}: no ref/5etools/books/{code}.json found", file=sys.stderr)
            continue
        total_cross_refs += len(result["cross_references"])
        total_unresolved += len(result["unresolved"])
        for fam, n in result.get("source_complete", {}).items():
            grand_source_complete[fam] = grand_source_complete.get(fam, 0) + n
        if result["empty"]:
            continue
        shard_path = os.path.join(SHARD_DIR, f"{code}.json")
        prov_path = os.path.join(SHARD_DIR, f"{code}.provenance.json")
        with open(shard_path, "w", encoding="utf-8") as f:
            json.dump(result["shard"], f, indent="\t", ensure_ascii=False)
            f.write("\n")
        with open(prov_path, "w", encoding="utf-8") as f:
            json.dump(result["provenance"], f, indent="\t", ensure_ascii=False)
            f.write("\n")
        books_written += 1
        for fam, n in result["stats"].items():
            grand_stats[fam] = grand_stats.get(fam, 0) + n
        sc = result.get("source_complete", {})
        sc_note = f" (of which source-complete: {sc})" if sc else ""
        print(f"{code}: " + ", ".join(f"{fam}={n}" for fam, n in sorted(result["stats"].items())) + sc_note)

    print()
    print("=" * 72)
    print(f"Books with >=1 entity: {books_written} / {len(all_codes)}")
    print("Totals by type:", grand_stats)
    print(f"Total entities: {sum(grand_stats.values())}")
    print(f"  of which via final source-complete sweep (no Markdown stub/heading/table/text mention found): {sum(grand_source_complete.values())}")
    print(f"  source-complete by type: {grand_source_complete}")
    print(f"Cross-references logged (passing mentions of other books' entities): {total_cross_refs}")
    print(f"Unresolved candidates (stub/heading/table seen, no ref/5etools-src match): {total_unresolved}")


if __name__ == "__main__":
    main()
