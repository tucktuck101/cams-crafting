#!/usr/bin/env python3
"""Extract `monster` and `legendaryGroup` entities from the 51 official D&D book
corpus into ref/5etools/shards/monsters/<SOURCE>.json.

INPUT-DATA CAVEAT (read this before touching the matching logic below):
Every one of the 51 books was scraped from the live 5etools site. Wherever the
original page embedded an existing bestiary stat block (the overwhelming majority
of every monster chapter, in every book that has monsters), the scrape only
captured the client-side-rendered placeholder skeleton - literally
`<i>Loading "<a ...>Name</a>"...</i>` - never the real AC/HP/ability-score/action
text. wave 1 (scripts/books/structure_books.py) already collapsed each such
placeholder pair into a clean `{"type":"statblock","tag":"creature","name":...,
"source":...}` node inside ref/5etools/books/<SRC>.json's bookData tree, but that
node carries no mechanical data - just the name and the source code the embed
pointed at. This was confirmed by grepping the entire ref/books/*.md corpus for
every real stat-block phrase (Armor Class/Hit Points/Melee Weapon Attack/Challenge/
Legendary Resistance/etc.) - with only a handful of exceptions (general glossary
prose, vehicle/siege-weapon features, DM-advice examples), none of it is attached
to an actual named monster anywhere in any of the 51 books.

Per project-lead policy for all wave-2 extractors: where the book's own text is
only a stub (or only a bare name mention), the entity is filled in from the
official, MIT-licensed 5etools dataset mirrored locally at
`ref/5etools-src/data/` (sparse clone of 5etools-mirror-3/5etools-src), matched
by exact name + the source the book's own embed/heading/table attributes it to -
never fabricated from model memory, and never imported into a book's shard
unless the book's own text (heading, stub, or table row) actually names that
entity. See the three `origin`/`match` values recorded per entity in the
sidecar for exactly how each one was resolved:
  - match="stub": heading had a (possibly foreign-sourced) statblock embed.
  - match="heading": heading text matches an official entity name, no embed.
  - match="table-mention": only found as a row in a same-book summary table.
  - match="cross-reference": heading reuses a different book's named entity
    via explicit prose ("uses the stat block of...", "appears in...", etc).
  - match="legendary-group-ref": legendaryGroup pulled in because an included
    monster's own `legendaryGroup` field pointed at it (same book as source).
  - match="legendary-group-standalone": legendaryGroup built directly from the
    book's own markdown text (lairActions/regionalEffects/mythicEncounter
    headings); used only when no official record exists for that name anywhere.
Monsters/legendaryGroups that are named in a book but have NEITHER a stub NOR
real mechanical text NOR any matching official record anywhere (e.g. Fizban's
Treasury of Dragons/"Adventure Atlas: The Mortuary"'s Planar Incarnate/Necrichor,
Thieves'-Gallery-style named NPCs with no official data at all) are left out and
reported as candidates-not-converted with the reason.
"""
from __future__ import annotations

import copy
import json
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BOOKS_JSON_DIR = REPO_ROOT / "ref" / "5etools" / "books"
SRC_DATA_DIR = REPO_ROOT / "ref" / "5etools-src" / "data"
BESTIARY_DIR = SRC_DATA_DIR / "bestiary"
SOURCES_JSON = REPO_ROOT / "ref" / "5etools" / "sources.json"
OUT_DIR = REPO_ROOT / "ref" / "5etools" / "shards" / "monsters"

GEN_TIME = int(time.time())

# ---------------------------------------------------------------------------
# Name normalization helpers
# ---------------------------------------------------------------------------

_TAG_STRIP_RE = re.compile(r"\{@(\w+)\s+([^{}|]+)(?:\|([^{}]*))?\}")


def strip_tags_to_text(s: str) -> str:
    def repl(m):
        inner, disp = m.group(2), m.group(3)
        return disp if disp else inner

    prev = None
    while prev != s:
        prev = s
        s = _TAG_STRIP_RE.sub(repl, s)
    return s


def normalize_name(name: str) -> str:
    name = strip_tags_to_text(name)
    name = name.replace("\u2019", "'").replace("\u2018", "'")
    name = re.sub(r"[*_]", "", name)
    name = name.strip().lower()
    name = re.sub(r"\s+", " ", name)
    return name


_ARTICLE_RE = re.compile(r"^(the|a|an)\s+", re.I)


def strip_article(n: str) -> str:
    return _ARTICLE_RE.sub("", n)


# ---------------------------------------------------------------------------
# Official reference data (ref/5etools-src), used ONLY to resolve entities that
# the book's own text already names (see module docstring).
# ---------------------------------------------------------------------------


class OfficialData:
    def __init__(self):
        index = json.load(open(BESTIARY_DIR / "index.json"))
        self.monsters_by_source: dict[str, dict[str, list[dict]]] = {}
        self.fluff_by_source: dict[str, dict[str, dict]] = {}
        for src, fname in index.items():
            path = BESTIARY_DIR / fname
            if not path.exists():
                continue
            data = json.load(open(path))
            d = defaultdict(list)
            for m in data.get("monster", []):
                d[normalize_name(m["name"])].append(m)
            self.monsters_by_source[src] = d
            fpath = BESTIARY_DIR / f"fluff-{fname}"
            if fpath.exists():
                fd = json.load(open(fpath))
                fdict = {}
                for f in fd.get("monsterFluff", []):
                    fdict[normalize_name(f["name"])] = f
                self.fluff_by_source[src] = fdict

        lg_data = json.load(open(BESTIARY_DIR / "legendarygroups.json"))
        self.lg_by_source: dict[str, dict[str, dict]] = defaultdict(dict)
        for lg in lg_data.get("legendaryGroup", []):
            self.lg_by_source[lg["source"]][normalize_name(lg["name"])] = lg

        # Flat global name -> [source,...] indices, used only for the
        # cross-reference and standalone-legendaryGroup-skip checks.
        self.monster_name_sources: dict[str, list[str]] = defaultdict(list)
        for src, d in self.monsters_by_source.items():
            for name in d:
                self.monster_name_sources[name].append(src)
        self.lg_name_sources: dict[str, list[str]] = defaultdict(list)
        for src, d in self.lg_by_source.items():
            for name in d:
                self.lg_name_sources[name].append(src)

    def find_monsters(self, source: str, heading_name: str, exact_only: bool = False):
        """Match heading_name against official monsters of `source` only.
        Returns a list (possibly empty) since one heading can cover several
        named variants (e.g. GGR's "### Rakdos Performer" heading covers
        three comma-suffixed variant stat blocks; BMT's "### Detention
        Drones" covers four prefix-varied ones; GGR's "#### Merfolk" heading
        covers the single official "Simic Merfolk"). With exact_only=True,
        only the exact/article-stripped match is attempted (used for a
        first priority pass so an exact heading always wins provenance over
        a fuzzy one matching the same official record from elsewhere)."""
        d = self.monsters_by_source.get(source)
        if not d:
            return []
        n = normalize_name(heading_name)
        if n in d:
            return [d[n][0]]
        n2 = strip_article(n)
        if n2 in d:
            return [d[n2][0]]
        if exact_only:
            return []
        n_words = n.split()
        n2_words = n2.split()
        # Singularize a bare trailing "s" for suffix/prefix word matching
        # (heading "Detention Drones" / official "...Detention Drone").
        n_sing_words = n_words[:-1] + [n_words[-1][:-1]] if n_words and n_words[-1].endswith("s") else n_words
        out = []
        for k, v in d.items():
            if "," in k:
                first = k.split(",")[0].strip()
                if first == n or first == n2:
                    out.append(v[0])
                    continue
            if re.search(r"(^|\W)" + re.escape(k) + r"($|\W)", n) or re.search(
                r"(^|\W)" + re.escape(k) + r"($|\W)", n2
            ):
                out.append(v[0])
                continue
            k_words = k.split()
            # Suffix-word match only (heading is a shorter/generic stem that
            # is the TRAILING words of a more specific official name, e.g.
            # heading "Detention Drones" vs official "Quadrone Detention
            # Drone", or heading "Merfolk" vs official "Simic Merfolk").
            # Deliberately NOT prefix-matching: a heading that is a real,
            # independently-meaningful shorter phrase (e.g. AATM's "Heralds
            # of Dust" faction heading) must not be treated as a hit just
            # because some unrelated, longer official name happens to START
            # with the same words (e.g. "Heralds of Dust Exorcist").
            for hw in (n_words, n2_words, n_sing_words):
                if hw and len(k_words) > len(hw) and k_words[-len(hw):] == hw:
                    out.append(v[0])
                    break
        # de-dup while preserving order
        seen = set()
        uniq = []
        for m in out:
            key = id(m)
            if key not in seen:
                seen.add(key)
                uniq.append(m)
        return uniq


    def find_monster_any_source(self, name: str, exclude_source: str | None = None):
        n = normalize_name(name)
        srcs = self.monster_name_sources.get(n, [])
        srcs = [s for s in srcs if s != exclude_source]
        if not srcs:
            return None
        return srcs


OFFICIAL = OfficialData()

# ---------------------------------------------------------------------------
# Book tree indexing: walk ref/5etools/books/<SRC>.json's bookData once,
# collecting every statblock stub, heading, table, and lair/regional/mythic
# sub-section.
# ---------------------------------------------------------------------------


def collect_strings(node, out):
    if isinstance(node, str):
        out.append(node)
    elif isinstance(node, dict):
        for k in ("entries", "items", "headerEntries", "footerEntries", "rows", "entry"):
            if k in node:
                collect_strings(node[k], out)
    elif isinstance(node, list):
        for v in node:
            collect_strings(v, out)


def direct_strings(node) -> str:
    """Only this heading's own paragraph text, not nested sub-heading text."""
    out = []
    for e in node.get("entries", []):
        if isinstance(e, str):
            out.append(e)
        elif isinstance(e, dict) and e.get("type") in ("list",):
            collect_strings(e, out)
    return " ".join(out)


_LAIR_FIELD_RE = {
    "lairActions": re.compile(r"^(additional )?lair actions?$", re.I),
    "regionalEffects": re.compile(r"^(additional )?regional effects?$", re.I),
}


class BookIndex:
    def __init__(self, src):
        self.src = src
        self.statblocks = []  # (name, source, section_id)
        self.headings = []  # (name, section_id, node)
        self.tables = []  # (rows, section_id)
        self.lair_nodes = []  # (field, owner_ctx, node)
        self.other_tag_names = set()  # normalized names claimed by a non-creature embed

    def walk(self, node, ctx):
        if isinstance(node, dict):
            name = node.get("name")
            nid = node.get("id", ctx[1] if ctx else None)
            ntype = node.get("type")
            new_ctx = ctx
            if ntype in ("section", "entries") and name:
                new_ctx = (name, nid)
                self.headings.append((name, nid, node))
                nlow = strip_tags_to_text(name).strip().lower()
                for field, pat in _LAIR_FIELD_RE.items():
                    if pat.match(nlow):
                        # Prefer the deepest matching node: skip registering
                        # this one if its own entries list directly nests
                        # another node matching the SAME field (a wrapping
                        # heading like VGM's "Hag Lair Actions" > "Lair
                        # Actions"); the inner one registers itself when the
                        # walk recurses into it.
                        inner = [
                            e
                            for e in node.get("entries", [])
                            if isinstance(e, dict)
                            and e.get("type") == "entries"
                            and pat.match(strip_tags_to_text(e.get("name", "")).strip().lower())
                        ]
                        if not inner:
                            self.lair_nodes.append((field, ctx, node))
                if "mythic encounter" in nlow:
                    self.lair_nodes.append(("mythicEncounter", ctx, node))
            if ntype == "statblock":
                if node.get("tag") == "creature":
                    self.statblocks.append((node.get("name"), node.get("source"), ctx[1] if ctx else nid))
                elif node.get("name"):
                    self.other_tag_names.add(normalize_name(node.get("name")))
            if ntype == "table":
                self.tables.append((node.get("rows", []), ctx[1] if ctx else nid))
            for k in ("entries", "items"):
                v = node.get(k)
                if isinstance(v, list):
                    for e in v:
                        self.walk(e, new_ctx)
        elif isinstance(node, list):
            for e in node:
                self.walk(e, ctx)


def build_index(src_code) -> BookIndex | None:
    path = BOOKS_JSON_DIR / f"{src_code}.json"
    if not path.exists():
        return None
    d = json.load(open(path))
    bd = d["bookData"][0]["data"]
    idx = BookIndex(src_code)
    idx.walk(bd, None)
    return idx


# ---------------------------------------------------------------------------
# legendaryGroup owner-name derivation + the generic/false-positive filter
# ---------------------------------------------------------------------------

_CREATURE_TYPE_WORDS = {
    "aberration", "beast", "celestial", "construct", "dragon", "elemental",
    "fey", "fiend", "giant", "humanoid", "monstrosity", "ooze", "plant",
    "undead", "vehicle",
}


def lair_node_owner_name(ctx) -> str | None:
    if not ctx:
        return None
    name = strip_tags_to_text(ctx[0]).strip()
    m = re.match(r"^(.*?)\s+Lair(?:s|\s+Actions?)?$", name, re.I)
    if m and m.group(1).strip():
        return m.group(1).strip()
    return name


def owner_is_generic(owner: str | None) -> bool:
    if not owner:
        return True
    lo = owner.strip().lower()
    if "creature" in lo:
        return True
    if lo in _CREATURE_TYPE_WORDS:
        return True
    if "hoard" in lo or "quirk" in lo:
        return True
    return False


def filter_lair_candidates(idx: BookIndex):
    """Group an index's raw lair_nodes by owning section, drop generic/
    false-positive ones, require lairActions or mythicEncounter to anchor a
    bare regionalEffects (see module docstring's rationale in the design
    notes: regionalEffects-only sections with no paired lairActions/mythic
    are reliably non-creature environmental text elsewhere in these books)."""
    by_ctx = defaultdict(dict)
    for field, ctx, node in idx.lair_nodes:
        cid = ctx[1] if ctx else id(ctx)
        by_ctx[cid].setdefault("owner", lair_node_owner_name(ctx))
        by_ctx[cid][field] = node
    out = {}
    for cid, d in by_ctx.items():
        owner = d.get("owner")
        if owner_is_generic(owner):
            continue
        if "lairActions" not in d and "mythicEncounter" not in d:
            continue
        out[cid] = d
    return out


# ---------------------------------------------------------------------------
# Cross-reference phrase detection (MOT-style "uses the stat block of X")
# ---------------------------------------------------------------------------

_CROSS_REF_RE = re.compile(
    r"\bstat ?block\b|\bstatistics are\b|\bstatistically identical\b|"
    r"\bidentical to the\b|\buses? the stat block\b|"
    r"\bsame stat block\b|\bas described in the\b",
    re.I,
)


def build_title_lookup(sources):
    out = []
    for b in sources:
        title = re.sub(r"\s*\(\d{4}\)\s*$", "", b["full"]).strip()
        out.append((title.lower(), b["source"]))
    out.sort(key=lambda x: -len(x[0]))
    return out


# ---------------------------------------------------------------------------
# legendaryGroup resolution (monster-driven + standalone fallback)
# ---------------------------------------------------------------------------


def strip_private(obj: dict) -> dict:
    obj = copy.deepcopy(obj)
    obj.pop("page", None)
    # Site-only convenience flags (SRD/Basic-Rules inclusion markers) aren't
    # part of the brew schema's property whitelist for either the bestiary
    # or legendarygroups defs - drop them rather than failing validation.
    for k in ("srd", "srd52", "basicRules", "basicRules2024"):
        obj.pop(k, None)
    return obj


def resolve_legendary_group(book_code: str, ref: dict, lg_out: dict, provenance: dict, depth=0):
    """Follow a monster's legendaryGroup {name, source} pointer. Only pulls it
    into this book's shard when the pointer's own source is this book (see
    module docstring); recursively resolves _copy base chains (same source)."""
    if depth > 4 or ref.get("source") != book_code:
        return
    name = ref.get("name")
    norm = normalize_name(name)
    if norm in lg_out:
        return
    lg = OFFICIAL.lg_by_source.get(book_code, {}).get(norm)
    if not lg:
        return
    lg_out[norm] = strip_private(lg)
    provenance[f"legendaryGroup:{name}"] = {
        "origin": "5etools-src",
        "match": "legendary-group-ref",
    }
    copy_ref = lg.get("_copy")
    if copy_ref:
        resolve_legendary_group(book_code, copy_ref, lg_out, provenance, depth + 1)


def resolve_standalone_lair_candidates(book_code: str, idx: BookIndex, lg_out: dict, provenance: dict):
    candidates = filter_lair_candidates(idx)
    for cid, d in candidates.items():
        owner = d["owner"]
        norm = normalize_name(owner)
        if norm in lg_out:
            continue
        same = OFFICIAL.lg_by_source.get(book_code, {})
        if norm in same:
            lg_out[norm] = strip_private(same[norm])
            provenance[f"legendaryGroup:{same[norm]['name']}"] = {
                "origin": "5etools-src",
                "match": "heading",
                "section": cid,
            }
            continue
        owner_words = norm.split()
        fuzzy_hit = None
        for cand_norm, cand in same.items():
            cw = cand_norm.split()
            if len(cw) > len(owner_words) and (
                cw[-len(owner_words):] == owner_words or cw[: len(owner_words)] == owner_words
            ):
                fuzzy_hit = cand
                break
        if fuzzy_hit:
            nn = normalize_name(fuzzy_hit["name"])
            if nn not in lg_out:
                lg_out[nn] = strip_private(fuzzy_hit)
                provenance[f"legendaryGroup:{fuzzy_hit['name']}"] = {
                    "origin": "5etools-src",
                    "match": "heading-fuzzy",
                    "section": cid,
                }
            continue
        foreign_sources = [s for s in OFFICIAL.lg_name_sources.get(norm, []) if s != book_code]
        if foreign_sources:
            continue  # true home is elsewhere; that book's own shard owns it
        # Nothing official anywhere under any name close to this one ->
        # genuinely book-native content (e.g. GGR's "Golgari"/"Rakdos
        # Carnival" group-lair mechanics, never formalized as a 5etools
        # legendaryGroup record) - build it straight from this book's own
        # (already wave-1-parsed) markdown entries.
        entry = {"name": owner, "source": book_code}
        for field in ("lairActions", "regionalEffects", "mythicEncounter"):
            if field in d:
                entry[field] = d[field]["entries"]
        lg_out[norm] = entry
        provenance[f"legendaryGroup:{owner}"] = {
            "origin": "markdown",
            "match": "legendary-group-standalone",
            "section": cid,
        }


# ---------------------------------------------------------------------------
# Per-book monster extraction
# ---------------------------------------------------------------------------


def extract_book(book_code: str, title_lookup, report: dict):
    idx = build_index(book_code)
    if idx is None:
        report["missing_book_json"].append(book_code)
        return None

    monsters_out: dict[str, dict] = {}  # normalized name -> monster dict
    provenance: dict[str, dict] = {}
    candidates_not_converted = []

    def include_monster(m: dict, match: str, section_id, data_from: str | None, origin="5etools-src"):
        norm = normalize_name(m["name"])
        if norm in monsters_out:
            return
        mm = strip_private(m)
        mm.pop("otherSources", None) if data_from else None
        if data_from:
            mm.pop("reprintedAs", None)
            mm.pop("_versions", None)
        mm["source"] = book_code
        fluff_src = data_from or book_code
        fl = OFFICIAL.fluff_by_source.get(fluff_src, {}).get(normalize_name(m["name"]))
        if fl and "fluff" not in mm:
            fluff_entries = fl.get("entries")
            if fluff_entries:
                mm["fluff"] = {"entries": fluff_entries}
        monsters_out[norm] = mm
        prov = {"origin": origin, "match": match, "section": section_id}
        if data_from:
            prov["data_from"] = data_from
        provenance[m["name"]] = prov

    # --- Pass 1: statblock stubs (own heading + embed, any source) ---
    id_to_name = {nid: strip_tags_to_text(name) for name, nid, node in idx.headings if nid}
    names_by_section: dict[str, set] = defaultdict(set)
    for name, src, section_id in idx.statblocks:
        if name and section_id:
            names_by_section[section_id].add(normalize_name(name))
    seen_stub_names = set()
    for name, src, section_id in idx.statblocks:
        if not name or not src:
            continue
        seen_stub_names.add(normalize_name(name))
        m = OFFICIAL.monsters_by_source.get(src, {}).get(normalize_name(name))
        if not m:
            # A family/group heading (e.g. MM's "Angels", covering Deva/
            # Planetar/Solar) carries its own shared "(Info)" flavor-blurb
            # embed titled after the GROUP itself, in addition to the real
            # per-individual statblock embeds - when that happens (this
            # stub's name matches its own enclosing heading AND the same
            # section also holds other, differently-named stub(s)), it is
            # noise, not a missing entity, so it's silently skipped rather
            # than reported as a candidate.
            if (
                normalize_name(name) == normalize_name(id_to_name.get(section_id, ""))
                and len(names_by_section.get(section_id, ())) > 1
            ):
                continue
            candidates_not_converted.append(
                {"name": name, "reason": f"statblock stub (source={src}) has no matching official record", "section": section_id}
            )
            continue
        m = m[0]
        include_monster(m, "stub", section_id, data_from=(src if src != book_code else None))

    # --- Pass 2: heading text, same-book official monsters only. Exact
    #     matches are swept first across every heading so a monster's own
    #     dedicated heading always wins provenance over some other, unrelated
    #     heading that merely fuzzy-matches the same name (e.g. a location
    #     heading that happens to quote the monster's name in a possessive). ---
    own_monsters = OFFICIAL.monsters_by_source.get(book_code, {})
    for name, nid, node in idx.headings:
        n = strip_tags_to_text(name)
        for m in OFFICIAL.find_monsters(book_code, n, exact_only=True):
            if normalize_name(m["name"]) not in monsters_out:
                include_monster(m, "heading", nid, data_from=None)
    for name, nid, node in idx.headings:
        n = strip_tags_to_text(name)
        for m in OFFICIAL.find_monsters(book_code, n):
            if normalize_name(m["name"]) not in monsters_out:
                include_monster(m, "heading", nid, data_from=None)

    # --- Pass 3: table-mention, same-book official monsters only ---
    for rows, section_id in idx.tables:
        for row in rows:
            cells = row if isinstance(row, list) else [row]
            for cell in cells:
                if not isinstance(cell, str):
                    continue
                for bm in re.findall(r"\{@b\s+([^{}|]+)\}", cell):
                    for m in OFFICIAL.find_monsters(book_code, bm):
                        if normalize_name(m["name"]) not in monsters_out:
                            include_monster(m, "table-mention", section_id, data_from=None)

    # --- Pass 4: cross-book heading reuse ("uses the stat block of X") ---
    for name, nid, node in idx.headings:
        n = strip_tags_to_text(name)
        norm = normalize_name(n)
        if norm in monsters_out:
            continue
        if OFFICIAL.monsters_by_source.get(book_code, {}).get(norm):
            continue  # already handled (or would have been) by pass 2
        text = direct_strings(node)
        if not text or not _CROSS_REF_RE.search(text):
            continue
        full_text_for_title = text.lower()
        chosen_source = None
        for title, code in title_lookup:
            if title and title in full_text_for_title and OFFICIAL.monsters_by_source.get(code, {}).get(norm):
                chosen_source = code
                break
        if not chosen_source:
            srcs = OFFICIAL.find_monster_any_source(n, exclude_source=book_code)
            if srcs:
                chosen_source = "MM" if "MM" in srcs else sorted(srcs)[0]
        if not chosen_source:
            continue
        m = OFFICIAL.monsters_by_source[chosen_source][norm][0]
        include_monster(m, "cross-reference", nid, data_from=chosen_source)

    # --- Pass 5: same-book text-mention anywhere (no heading/table needed).
    #     Still same-book-only and still anchored on the book's own small,
    #     finite official monster set, so this cannot pull in an unrelated
    #     creature merely because its name happens to appear in prose - the
    #     candidate pool is only ever "things WotC's own data says this
    #     exact book published." Catches e.g. DMG's "Larva" (an officially
    #     DMG-sourced monster discussed only in a plain, un-headed paragraph
    #     about the plane of Hades, with no table/heading/stub at all). ---
    if own_monsters:
        full_blob = " ".join(direct_strings(node) for _, _, node in idx.headings)
        full_blob_norm = normalize_name(full_blob)
        for norm, ms in own_monsters.items():
            if norm in monsters_out:
                continue
            if norm in idx.other_tag_names:
                continue  # name is claimed by a different entity type's embed in this same book (e.g. an item of the same name) - too ambiguous to trust a bare text mention
            if re.search(r"(^|\W)" + re.escape(norm) + r"($|\W)", full_blob_norm):
                include_monster(ms[0], "text-mention", None, data_from=None)

    # --- Pass 6 (final completeness rule): import every remaining official
    #     record whose own source equals this book, even with zero textual
    #     trace - covers chapters reduced by the scrape to a single pointer
    #     sentence (e.g. "See the full list on the Monsters page"). ---
    source_complete_count = 0
    for norm, ms in own_monsters.items():
        if norm not in monsters_out:
            include_monster(ms[0], "source-complete", None, data_from=None)
            source_complete_count += 1

    container_ids = {sid for _, _, sid in idx.statblocks if sid}
    _BESTIARY_CTX_RE = re.compile(
        r"\bcreatures\b|\bstat blocks\b|\brogues.? gallery\b|\bappendix\b.*\bcreatures\b", re.I
    )
    for name, nid, node in idx.headings:
        n = strip_tags_to_text(name)
        norm = normalize_name(n)
        if norm in monsters_out or norm in seen_stub_names or owner_is_generic(n):
            continue
        if nid in container_ids:
            continue  # this heading is itself a group header whose children are already-extracted statblocks (e.g. MM's "Angels"/"Dragons" family headings), not a missing entity in its own right
        if not nid or "/" not in nid:
            continue
        parent_name = id_to_name.get(nid.rsplit("/", 1)[0])
        if not parent_name or not _BESTIARY_CTX_RE.search(parent_name):
            continue  # only flag headings nested under an explicit creature-listing/appendix-style parent section - everything else (generic "monster"/"NPC" rules-text chapters) is noise
        text = direct_strings(node)
        if len(text) < 40:
            continue
        if OFFICIAL.find_monster_any_source(n):
            continue  # exists officially elsewhere but wasn't a confident cross-reference match (see pass 4)
        candidates_not_converted.append(
            {
                "name": n,
                "reason": "heading nested under a bestiary/appendix-style section, has real body text, but no stub and no matching official record under any source",
                "section": nid,
            }
        )


    # --- legendaryGroup resolution ---
    lg_out: dict[str, dict] = {}
    for norm, m in list(monsters_out.items()):
        ref = m.get("legendaryGroup")
        if isinstance(ref, dict):
            resolve_legendary_group(book_code, ref, lg_out, provenance)
    resolve_standalone_lair_candidates(book_code, idx, lg_out, provenance)

    # Final completeness rule also applies to legendaryGroup: pull in any
    # remaining officially-same-sourced record we haven't already picked up
    # via a monster's own legendaryGroup reference or the markdown fallback.
    lg_source_complete = 0
    for norm, lg in OFFICIAL.lg_by_source.get(book_code, {}).items():
        if norm not in lg_out:
            lg_out[norm] = strip_private(lg)
            provenance[f"legendaryGroup:{lg['name']}"] = {
                "origin": "5etools-src",
                "match": "source-complete",
            }
            lg_source_complete += 1
            copy_ref = lg.get("_copy")
            if copy_ref:
                resolve_legendary_group(book_code, copy_ref, lg_out, provenance)

    return {
        "monsters": list(monsters_out.values()),
        "legendaryGroups": list(lg_out.values()),
        "provenance": provenance,
        "candidates_not_converted": candidates_not_converted,
        "stub_count": len(idx.statblocks),
        "heading_count": len(idx.headings),
        "table_count": len(idx.tables),
        "source_complete_count": source_complete_count,
        "lg_source_complete_count": lg_source_complete,
    }


# ---------------------------------------------------------------------------
# Main driver
# ---------------------------------------------------------------------------


def main():
    sources = json.load(open(SOURCES_JSON))["books"]
    title_lookup = build_title_lookup(sources)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    report = {
        "missing_book_json": [],
        "per_book": {},
    }

    total_monsters = 0
    total_lg = 0
    match_type_counts = Counter()
    origin_counts = Counter()

    for b in sources:
        code = b["source"]
        result = extract_book(code, title_lookup, report)
        if result is None:
            continue
        if not result["monsters"] and not result["legendaryGroups"]:
            report["per_book"][code] = {
                "monsters": 0,
                "legendaryGroups": 0,
                "candidates_not_converted": len(result["candidates_not_converted"]),
                "stub_count": result["stub_count"],
            }
            continue

        book_json = json.load(open(BOOKS_JSON_DIR / f"{code}.json"))
        meta = {
            "sources": book_json["_meta"]["sources"],
            "edition": book_json["_meta"].get("edition", "classic"),
            "dateAdded": GEN_TIME,
            "dateLastModified": GEN_TIME,
        }
        out = {"_meta": meta}
        if result["monsters"]:
            out["monster"] = result["monsters"]
        if result["legendaryGroups"]:
            out["legendaryGroup"] = result["legendaryGroups"]

        out_path = OUT_DIR / f"{code}.json"
        with open(out_path, "w") as f:
            json.dump(out, f, indent="\t", ensure_ascii=False)
            f.write("\n")

        prov_path = OUT_DIR / f"{code}.provenance.json"
        with open(prov_path, "w") as f:
            json.dump(result["provenance"], f, indent="\t", ensure_ascii=False)
            f.write("\n")

        for p in result["provenance"].values():
            match_type_counts[p["match"]] += 1
            origin_counts[p["origin"]] += 1

        total_monsters += len(result["monsters"])
        total_lg += len(result["legendaryGroups"])
        report["per_book"][code] = {
            "monsters": len(result["monsters"]),
            "legendaryGroups": len(result["legendaryGroups"]),
            "candidates_not_converted": len(result["candidates_not_converted"]),
            "candidates_detail": result["candidates_not_converted"],
            "stub_count": result["stub_count"],
            "source_complete_monsters": result["source_complete_count"],
            "source_complete_legendary_groups": result["lg_source_complete_count"],
        }

    print(f"Total monsters: {total_monsters}")
    print(f"Total legendaryGroups: {total_lg}")
    print(f"Match types: {dict(match_type_counts)}")
    print(f"Origins: {dict(origin_counts)}")
    print(f"Missing book json: {report['missing_book_json']}")

    with open(OUT_DIR / "_extraction_report.json", "w") as f:
        json.dump(report, f, indent="\t", ensure_ascii=False)
        f.write("\n")


if __name__ == "__main__":
    main()
