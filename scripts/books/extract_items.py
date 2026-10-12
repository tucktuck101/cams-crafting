#!/usr/bin/env python3
"""Extract `item` / `baseitem` / `magicvariant` / `itemGroup` entities from the
51 official books into per-book homebrew-shaped shards under
`ref/5etools/shards/items/<SOURCE>.json`, with a provenance sidecar per book
(`ref/5etools/shards/items/<SOURCE>.provenance.json`).

INPUT: this reads the already-structured `ref/5etools/books/<SOURCE>.json`
bookData (wave 1's output), not the raw `ref/books/*.md` files directly. Wave
1 already converted markdown tables/paragraphs/embed-stubs into clean JSON
(`type:"table"`, `type:"entries"` bold-italic lead-ins, and
`type:"statblock",tag:"item"` nodes reconstructed from the scraped site's
"Loading ..." HTML placeholders) with stable `<SOURCE>:<slug/path>` section
ids - reusing that structure avoids re-deriving table/paragraph parsing and
keeps section-id provenance consistent with `ref/5etools/sections.jsonl`.

Why some entities come from ref/5etools-src instead of the book's own prose:
roughly 40/51 books were scraped from the live 5etools site's book-reader
pages. Wherever the ORIGINAL PRINTED PAGE embeds a magic item's full stat
block, the site renders it as a client-side "statblock transclusion" widget
that pulls the real text from the site's shared items.json at view time - a
static HTML scrape only captures the "Loading ..." placeholder, never the
actual rules text. So for ~309 magic items across 14 books, the book's own
full entry text is NOT recoverable from our corpus at all; per project
policy, those are instead filled from a local sparse clone of the official
5etools data (`ref/5etools-src/data/{items,items-base,magicvariants}.json`),
matched by EXACT (name, source) - never fabricated, never guessed. A few
further items are only named in a same-book summary table (e.g. GGR's
per-guild tables, SCC's "Magic Items for Sale") with no stub at all; those
are resolved the same way, but ONLY when the table's own source marker for
that row names the book being processed (otherwise it is logged as a
cross-reference, not imported).

Where a book's own prose DOES contain the full text (PHB/RMR's equipment
chapter tables, DMG's Firearms/Explosives/Poisons tables, SCAG's new
instrument list, VGM's/BMT's handful of narratively-embedded magic items),
this script parses that text directly instead, and tags the result
`origin: "markdown"`.

Python 3.9 stdlib only.
"""
from __future__ import annotations

import json
import re
import time
from collections import defaultdict
from copy import deepcopy
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BOOKS_JSON_DIR = REPO_ROOT / "ref/5etools/books"
SOURCES_JSON = REPO_ROOT / "ref/5etools/sources.json"
SRC_DATA_DIR = REPO_ROOT / "ref/5etools-src/data"
SHARD_DIR = REPO_ROOT / "ref/5etools/shards/items"
BREW_SCHEMA_DIR = REPO_ROOT / "ref/5etools/tooling/node_modules/5etools-utils/schema/brew"

GEN_TIME = int(time.time())

# ---------------------------------------------------------------------------
# 0. Load official reference data (ground truth for stub/table-mention fills)
# ---------------------------------------------------------------------------


def norm(s):
    return s.strip().lower() if isinstance(s, str) else s


def mv_source(mv):
    return mv.get("source") or mv.get("inherits", {}).get("source")

def load_allowed_props():
    """ref/5etools-src is the SITE's own data, which carries several
    site-only administrative fields (`srd`, `srd52`, `basicRules`,
    `basicRules2024`, etc.) that the brew/homebrew schema's
    `additionalProperties:false` objects don't allow. Derive the exact
    allowed top-level key sets straight from the same patched brew schema
    `validate.sh` checks against, so copied records are filtered correctly
    even if the site adds more such fields later."""
    items_schema = json.loads((BREW_SCHEMA_DIR / "items.json").read_text(encoding="utf-8"))
    base_schema = json.loads((BREW_SCHEMA_DIR / "items-base.json").read_text(encoding="utf-8"))
    mv_schema = json.loads((BREW_SCHEMA_DIR / "magicvariants.json").read_text(encoding="utf-8"))
    item_props = set(items_schema["$defs"]["itemData"]["properties"].keys())
    itemgroup_props = set(items_schema["$defs"]["itemGroup"]["anyOf"][0]["properties"].keys())
    baseitem_props = set(base_schema["$defs"]["baseitem"]["anyOf"][0]["properties"].keys())
    mv_site = mv_schema["$defs"]["_magicvariantSite"]["properties"]
    mv_root_rarity = mv_schema["$defs"]["_magicvariantBrewRootRarity"]["properties"]
    mv_top_props = set(mv_site.keys()) | set(mv_root_rarity.keys())
    mv_inherits_props = set(mv_site["inherits"].get("properties", {}).keys())
    return {
        "item": item_props, "itemGroup": itemgroup_props, "baseitem": baseitem_props,
        "magicvariant": mv_top_props, "magicvariant_inherits": mv_inherits_props,
    }



def load_official_indices():
    items_doc = json.loads((SRC_DATA_DIR / "items.json").read_text(encoding="utf-8"))
    base_doc = json.loads((SRC_DATA_DIR / "items-base.json").read_text(encoding="utf-8"))
    mv_doc = json.loads((SRC_DATA_DIR / "magicvariants.json").read_text(encoding="utf-8"))
    idx_item = {(norm(r["name"]), norm(r["source"])): r for r in items_doc["item"]}
    idx_itemgroup = {(norm(r["name"]), norm(r["source"])): r for r in items_doc["itemGroup"]}
    idx_baseitem = {(norm(r["name"]), norm(r["source"])): r for r in base_doc["baseitem"]}
    idx_mv = {(norm(r["name"]), norm(mv_source(r))): r for r in mv_doc["magicvariant"]}
    return idx_item, idx_itemgroup, idx_baseitem, idx_mv


def resolve_official(name, source, indices):
    idx_item, idx_itemgroup, idx_baseitem, idx_mv = indices
    key = (norm(name), norm(source))
    if key in idx_item:
        return "item", idx_item[key]
    if key in idx_itemgroup:
        return "itemGroup", idx_itemgroup[key]
    if key in idx_baseitem:
        return "baseitem", idx_baseitem[key]
    if key in idx_mv:
        return "magicvariant", idx_mv[key]
    return None, None


ALLOWED_PROPS = load_allowed_props()


def clean_official_copy(kind, rec, book_source):
    """Deep-copy an official record for re-use under `book_source`: strip the
    page number (our markdown corpus carries no page numbers), retarget the
    entity's effective source to this book, and drop any site-only
    administrative field (`srd`, `basicRules`, `hasToken`, ...) the brew
    schema's `additionalProperties:false` doesn't allow."""
    rec = deepcopy(rec)
    rec.pop("page", None)
    if kind == "magicvariant":
        for key in list(rec.keys()):
            if key not in ALLOWED_PROPS["magicvariant"]:
                del rec[key]
        inh = rec.get("inherits")
        if isinstance(inh, dict):
            inh.pop("page", None)
            for key in list(inh.keys()):
                if key not in ALLOWED_PROPS["magicvariant_inherits"]:
                    del inh[key]
            if "source" in inh:
                inh["source"] = book_source
        if "source" in rec:
            rec["source"] = book_source
    else:
        for key in list(rec.keys()):
            if key not in ALLOWED_PROPS[kind]:
                del rec[key]
        rec["source"] = book_source
    return rec


def base_name_variants(name_lower):
    """Normalize a name for dedup/cross-matching: official data sometimes
    prefixes a bonus item's canonical name with "+1 "/"+2 "/"+3 " (e.g. "+1
    All-Purpose Tool") or suffixes a size/variant qualifier in parens (e.g.
    "Barrier Tattoo (Small)") where a book's own summary table just says the
    bare family name ("All-Purpose Tool" / "Barrier Tattoo"); official armor
    names also disambiguate with a trailing " armor" the book's own table
    doesn't print (e.g. "Padded" in the PHB table vs. official "Padded
    Armor")."""
    variants = {name_lower}
    v = re.sub(r"^\+\d+\s+", "", name_lower)
    variants.add(v)
    variants.add(re.sub(r"\s*\([^)]*\)\s*$", "", v).strip())
    variants.add(re.sub(r"\s*\([^)]*\)\s*$", "", name_lower).strip())
    for variant in list(variants):
        variants.add(re.sub(r"\s+armor$", "", variant).strip())
    return variants


# ---------------------------------------------------------------------------
# 1. Tree-walking + tag-stripping helpers over wave 1's bookData JSON
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"\{@(\w+)\s+([^{}]*)\}")


def strip_tags(s):
    """Flatten 5etools {@tag display|source|...} markup down to its display
    text (repeatedly, to unwrap nested tags like {@b {@i x}})."""
    if not isinstance(s, str):
        return s
    prev = None
    while prev != s:
        prev = s
        s = _TAG_RE.sub(lambda m: m.group(2).split("|")[0], s)
    return s.strip()


def walk_tree(entries, cur_id=None, container=None):
    """Yield (node, nearest_id, immediate_container) for every dict node in a
    bookData entries tree. `immediate_container` is the parent node whose
    `entries` list directly holds `node` (None at the root) - used to recover
    a table's enclosing named section without a separate parent-pointer
    pass."""
    for e in entries:
        if isinstance(e, dict):
            nid = e.get("id", cur_id)
            yield e, nid, container
            if isinstance(e.get("entries"), list):
                yield from walk_tree(e["entries"], nid, e)


def all_tables(entries):
    for node, nid, container in walk_tree(entries):
        if node.get("type") == "table":
            yield node, nid, container


def find_section_by_name(entries, target_name):
    """Top-level chapter lookup: wave 1 marks H1 chapter headings with
    `type:"section"` (vs `type:"entries"` for everything nested under them),
    so matching on both avoids colliding with an unrelated nested heading
    that happens to share the same text (e.g. PHB's "5. Choose Equipment"
    character-creation step vs the real "Equipment" chapter)."""
    for node, _nid, _container in walk_tree(entries):
        if node.get("type") == "section" and node.get("name") == target_name:
            return node
    return None


def find_by_name(entries, target_name):
    for node, _nid, _container in walk_tree(entries):
        if node.get("name") == target_name:
            return node
    return None


def build_parent_map(entries, parent=None, pmap=None):
    if pmap is None:
        pmap = {}
    for e in entries:
        if isinstance(e, dict):
            pmap[id(e)] = parent
            if isinstance(e.get("entries"), list):
                build_parent_map(e["entries"], e, pmap)
    return pmap


def nearest_chapter_ancestor(node, pmap):
    """Walk up the parent map to the nearest `type:"section"` ancestor (the
    enclosing H1 chapter), or the highest ancestor reachable if none is
    marked `section` (defensive fallback)."""
    cur = node
    highest = node
    while cur is not None:
        if cur.get("type") == "section":
            return cur
        highest = cur
        cur = pmap.get(id(cur))
    return highest


def collect_leadins(section_node):
    """Collect every `{"type":"entries","name":X,"entries":[...]}` descendant
    of a section as {name.lower(): entries_list} - these are the
    `***Name.*** description` bold-italic lead-in paragraphs wave 1 already
    promoted to named sub-entries (per-item/-category flavour text that
    follows a PHB/DMG-style price table, possibly under a sibling sub-heading
    rather than inside the table's own immediate container - e.g. PHB's
    "Light/Medium/Heavy Armor" per-piece blurbs are siblings of the "Armor"
    table node, both children of "Armor and Shields")."""
    out = {}
    for node, _nid, _container in walk_tree(section_node.get("entries", [])):
        if node.get("type") == "entries" and node.get("name") and isinstance(node.get("entries"), list):
            out.setdefault(norm(node["name"]), node["entries"])
    return out


# ---------------------------------------------------------------------------
# 2. Cost / weight / damage / property text parsing (PHB/DMG table cells)
# ---------------------------------------------------------------------------

COIN_TO_CP = {"cp": 1, "sp": 10, "ep": 50, "gp": 100, "pp": 1000}
_COST_RE = re.compile(r"([\d,]+(?:\.\d+)?)\s*(cp|sp|ep|gp|pp)\b", re.I)
_MULT_RE = re.compile(r"^[\u00d7x]\s*(\d+)$")
_FRAC_CHARS = {"\u00bd": 0.5, "\u2153": 1 / 3, "\u2154": 2 / 3, "\u00bc": 0.25, "\u00be": 0.75}
DMG_TYPE_CODE = {
    "acid": "A", "bludgeoning": "B", "cold": "C", "fire": "F", "force": "O",
    "lightning": "L", "necrotic": "N", "piercing": "P", "poison": "I",
    "psychic": "Y", "radiant": "R", "slashing": "S", "thunder": "T",
}
PROPERTY_MAP = {
    "ammunition": "A", "finesse": "F", "heavy": "H", "light": "L", "loading": "LD",
    "reach": "R", "special": "S", "thrown": "T", "two-handed": "2H", "versatile": "V",
    "reload": "RLD", "burst fire": "BF|DMG",
}


def parse_number(s):
    s = s.strip()
    total = 0.0
    found = False
    for ch, val in _FRAC_CHARS.items():
        if s.endswith(ch):
            total += val
            s = s[: -len(ch)].strip()
            found = True
            break
    if s:
        if re.match(r"^\d+/\d+$", s):
            num, den = s.split("/")
            total += float(num) / float(den)
            found = True
        else:
            try:
                total += float(s.replace(",", ""))
                found = True
            except ValueError:
                pass
    return total if found else None


def parse_cost(text):
    """-> (value_in_cp, value_mult, ok). ok=False means the cell had content
    that isn't a recognised coin amount, dash, or "xN" multiplier (used to
    reject non-mechanical/joke table rows rather than silently zero them)."""
    text = strip_tags(text)
    if not text or text in ("\u2014", "-", ""):
        return None, None, True
    m = _MULT_RE.match(text.strip())
    if m:
        return None, float(m.group(1)), True
    m = _COST_RE.search(text)
    if not m:
        return None, None, False
    amount = float(m.group(1).replace(",", ""))
    cp = amount * COIN_TO_CP[m.group(2).lower()]
    return (int(cp) if cp == int(cp) else cp), None, True


def parse_weight(text):
    text = strip_tags(text)
    if not text or "\u2014" in text:
        return None, None, True
    m = _MULT_RE.match(text.strip())
    if m:
        return None, float(m.group(1)), True
    text2 = re.sub(r"\([^)]*\)", "", text)
    m = re.search(r"([\d,./\u00bd\u2153\u2154\u00bc\u00be]+)\s*lb", text2, re.I)
    if not m:
        return None, None, False
    return parse_number(m.group(1)), None, True


def parse_damage(text):
    """-> (dice, dmgType, ok)."""
    text = strip_tags(text)
    if not text or text in ("\u2014", "-", ""):
        return None, None, True
    m = re.match(r"^(\d+d\d+(?:\s*[+-]\s*\d+)?|\d+)\s+(\w+)", text)
    if not m:
        return None, None, False
    dtype = DMG_TYPE_CODE.get(m.group(2).lower())
    if dtype is None:
        return None, None, False
    return re.sub(r"\s+", "", m.group(1)), dtype, True


def parse_properties(text, rec):
    text = strip_tags(text)
    if not text or text in ("\u2014", "-"):
        return []
    props = []
    for tok in text.split(","):
        tok = tok.strip()
        if not tok:
            continue
        m = re.match(r"^([A-Za-z][A-Za-z \-]*?)(?:\s*\(([^)]*)\))?$", tok)
        if not m:
            continue
        word = m.group(1).strip().lower()
        paren = (m.group(2) or "").strip()
        code = PROPERTY_MAP.get(word)
        if not code:
            continue
        props.append(code)
        if word in ("thrown", "ammunition") and paren.lower().startswith("range"):
            rec["range"] = paren[5:].strip()
        elif word == "versatile" and paren:
            rec["dmg2"] = paren
        elif word == "reload" and paren:
            mnum = re.search(r"\d+", paren)
            if mnum:
                rec["reload"] = int(mnum.group())
    return props


def split_trade_good_phrase(phrase):
    """'1 lb. of flour or one chicken' -> two candidate goods; handles a
    weight/unit carried across a bare continuation clause, e.g. '1 lb. of
    cinnamon or pepper, or one sheep' gives cinnamon AND pepper 1 lb each."""
    results = []
    carry_qty_s, carry_unit = None, None
    for part in re.split(r"\s+or\s+", phrase.strip()):
        part = part.strip().rstrip(",").strip()
        if not part:
            continue
        m = re.match(r"^([\d./]+)\s*(lb\.?|sq\.\s*yd\.?)\s+of\s+(.+)$", part, re.I)
        if m:
            qty_s, unit, name = m.groups()
            carry_qty_s, carry_unit = qty_s, unit
            name = name.strip().capitalize()
        else:
            m2 = re.match(r"^one\s+(.+)$", part, re.I)
            if m2:
                results.append({"name": m2.group(1).strip().capitalize()})
                continue
            name, qty_s, unit = part.capitalize(), carry_qty_s, carry_unit
        if qty_s is not None and unit:
            if unit.lower().startswith("lb"):
                results.append({"name": name, "weight": parse_number(qty_s)})
            else:
                results.append({"name": name, "weightNote": f"{qty_s} {unit}"})
        else:
            results.append({"name": name})
    return results


# ---------------------------------------------------------------------------
# 3. Pipeline A: `{"type":"statblock","tag":"item",...}` stub resolution
# ---------------------------------------------------------------------------


def extract_stub_entities(bdata, book_source, indices, provenance, not_converted):
    found = defaultdict(list)
    for node, nid, _container in walk_tree(bdata):
        if node.get("type") != "statblock" or node.get("tag") != "item":
            continue
        name, osrc = node.get("name"), node.get("source")
        kind, rec = resolve_official(name, osrc, indices)
        if not kind:
            not_converted.append({
                "name": name, "section_id": nid,
                "reason": f"statblock embed present (source={osrc}) but no matching record exists in "
                          f"ref/5etools-src/data for that exact name+source; book prose for this item is a "
                          f"client-rendered placeholder only, so no text is recoverable",
            })
            continue
        cleaned = clean_official_copy(kind, rec, book_source)
        data_from = osrc if norm(osrc) != norm(book_source) else None
        found[kind].append(cleaned)
        prov = {"origin": "5etools-src", "match": "stub", "section_id": nid}
        if data_from:
            prov["data_from"] = data_from
        provenance.setdefault(kind, {})[cleaned["name"]] = prov
    return found


# ---------------------------------------------------------------------------
# 4. Pipeline B: fully inline magic items (type/rarity line + prose, no stub)
# ---------------------------------------------------------------------------

_TYPE_LINE_RE = re.compile(r"^\{@i\s+(.+)\}$")
_RARITY_IN_LINE_RE = re.compile(
    r"^(.*?),\s*(common|uncommon|rare|very rare|legendary|artifact|unknown \(magic\)|unknown|varies|none)\b(.*)$",
    re.I,
)


def classify_item_type(category_text):
    low = category_text.strip().lower()
    if low.startswith("wondrous"):
        return "W", True
    if low.startswith("weapon"):
        return ("R" if re.search(r"\b(bow|crossbow|sling|blowgun|firearm|gun)\b", low) else "M"), False
    if low.startswith("armor"):
        if "shield" in low:
            return "S", False
        for word, code in (("heavy", "HA"), ("medium", "MA"), ("light", "LA")):
            if word in low:
                return code, False
        return None, False
    if low.startswith("potion"):
        return "P", False
    if low.startswith("ring"):
        return "RG|DMG", False
    if low.startswith("rod"):
        return "RD|DMG", False
    if low.startswith("wand"):
        return "WD|DMG", False
    if low.startswith("scroll") or low.startswith("spell scroll"):
        return "SC|DMG", False
    return None, False


def parse_inline_item_node(node, book_source):
    entries = node.get("entries") or []
    if not entries or not isinstance(entries[0], str):
        return None
    m = _TYPE_LINE_RE.match(entries[0].strip())
    if not m:
        return None
    rm = _RARITY_IN_LINE_RE.match(m.group(1))
    if not rm:
        return None
    item = {"name": node["name"], "source": book_source, "rarity": rm.group(2).strip().lower()}
    type_code, wondrous = classify_item_type(rm.group(1).strip())
    if type_code:
        item["type"] = type_code
    if wondrous:
        item["wondrous"] = True
    attune_m = re.search(r"\(requires attunement([^)]*)\)", rm.group(3), re.I)
    if attune_m:
        detail = attune_m.group(1).strip()
        item["reqAttune"] = detail if detail.startswith("by") else True
    body = entries[1:]
    if body:
        item["entries"] = body
    return item


def extract_inline_items(bdata, book_source, provenance, already_captured):
    found = []
    for node, nid, _container in walk_tree(bdata):
        if node.get("type") != "entries" or not node.get("name"):
            continue
        if already_captured(node["name"]):
            continue
        item = parse_inline_item_node(node, book_source)
        if item:
            found.append(item)
            provenance.setdefault("item", {})[item["name"]] = {
                "origin": "markdown", "match": "inline-full-text", "section_id": nid,
            }
    return found


# ---------------------------------------------------------------------------
# 5. Pipeline C: same-book summary ("Rarity"+"Item"/"Name") table mentions
# ---------------------------------------------------------------------------


def find_rarity_item_tables(bdata):
    for node, nid, _container in all_tables(bdata):
        labels = [strip_tags(l).strip().lower() for l in (node.get("colLabels") or [])]
        if "rarity" not in labels:
            continue
        name_col = next((labels.index(c) for c in ("item", "name", "magic item") if c in labels), None)
        if name_col is None:
            continue
        yield node, nid, name_col, labels.index("rarity"), (labels.index("source") if "source" in labels else None)


def extract_table_mention_entities(bdata, book_source, indices, provenance, cross_refs, not_converted,
                                    already_captured, mark_captured):
    found = defaultdict(list)
    for table, nid, name_col, _rarity_col, source_col in find_rarity_item_tables(bdata):
        for row in table.get("rows", []):
            if name_col >= len(row):
                continue
            name = strip_tags(row[name_col])
            if not name or already_captured(name):
                continue
            claimed_source = strip_tags(row[source_col]) if source_col is not None and source_col < len(row) else None
            if not claimed_source:
                m = re.search(r"\(([A-Za-z0-9]{2,8})\)\s*$", name)
                if m:
                    claimed_source, name = m.group(1), name[: m.start()].strip()
            if not claimed_source:
                claimed_source = book_source
            kind, rec = resolve_official(name, claimed_source, indices)
            if norm(claimed_source) != norm(book_source):
                cross_refs.append({
                    "name": name, "source": claimed_source, "section_id": nid,
                    "note": "mentioned in a same-book summary table but belongs to another sourcebook; not imported",
                })
                continue
            if not kind:
                not_converted.append({
                    "name": name, "section_id": nid,
                    "reason": "named in this book's own summary table (rarity+item) but no matching official "
                              "record exists under this source and no stub/full text is present either",
                })
                continue
            cleaned = clean_official_copy(kind, rec, book_source)
            if already_captured(cleaned["name"]):
                continue
            mark_captured(cleaned["name"])
            found[kind].append(cleaned)
            provenance.setdefault(kind, {})[cleaned["name"]] = {
                "origin": "5etools-src", "match": "table-mention", "section_id": nid,
            }
    return found


# ---------------------------------------------------------------------------
# 6. Pipeline D: PHB/RMR equipment-chapter tables (fully present prose)
# ---------------------------------------------------------------------------


def classify_weapon_category(text):
    low = text.lower()
    cat = "martial" if "martial" in low else ("simple" if "simple" in low else None)
    typ = "R" if "ranged" in low else ("M" if "melee" in low else None)
    return cat, typ


def is_row_blank_except_name(row, name_idx=0):
    return all((not strip_tags(c).strip()) for i, c in enumerate(row) if i != name_idx)


def process_weapon_table(table, book_source, section_id, leadins, not_converted):
    out = []
    cur_cat, cur_type = classify_weapon_category(table.get("caption") or "")
    for row in table.get("rows", []):
        name = strip_tags(row[0])
        if not name:
            continue
        if is_row_blank_except_name(row):
            cat, typ = classify_weapon_category(name)
            cur_cat, cur_type = cat or cur_cat, typ or cur_type
            continue
        cost_raw = row[1] if len(row) > 1 else ""
        dmg_raw = row[2] if len(row) > 2 else ""
        weight_raw = row[3] if len(row) > 3 else ""
        props_raw = row[4] if len(row) > 4 else ""
        value, value_mult, cost_ok = parse_cost(cost_raw)
        weight, weight_mult, weight_ok = parse_weight(weight_raw)
        dice, dtype, dmg_ok = parse_damage(dmg_raw)
        if not (cost_ok and weight_ok and dmg_ok):
            not_converted.append({
                "name": name, "section_id": section_id,
                "reason": "weapon table row has a non-mechanical cost/weight/damage value "
                          f"(cost={cost_raw!r}, weight={weight_raw!r}, damage={dmg_raw!r}); "
                          "not a real D&D stat line, skipped rather than guessed",
            })
            continue
        rec = {"name": name, "source": book_source, "rarity": "none", "type": cur_type or "M"}
        if cur_cat:
            rec["weaponCategory"] = cur_cat
        if value is not None:
            rec["value"] = value
        if value_mult is not None:
            rec["valueMult"] = value_mult
        if weight is not None:
            rec["weight"] = weight
        if weight_mult is not None:
            rec["weightMult"] = weight_mult
        if dice:
            rec["dmg1"] = dice
        if dtype:
            rec["dmgType"] = dtype
        props = parse_properties(props_raw, rec)
        if props:
            rec["property"] = props
        lead = leadins.get(norm(name))
        if lead:
            rec["entries"] = lead
        out.append(rec)
    return out


def classify_armor_category(text):
    low = text.lower()
    if "shield" in low:
        return "S"
    for word, code in (("heavy", "HA"), ("medium", "MA"), ("light", "LA")):
        if word in low:
            return code
    return None


def process_armor_table(table, book_source, leadins, initial_context="", not_converted=None):
    labels = [strip_tags(l).strip().lower() for l in (table.get("colLabels") or [])]

    def col(*names):
        return next((labels.index(n) for n in names if n in labels), None)

    i_cost, i_ac = col("cost"), col("armor class (ac)", "ac")
    i_str, i_stealth, i_weight = col("strength"), col("stealth"), col("weight")
    out = []
    cur_type = classify_armor_category(initial_context)
    for row in table.get("rows", []):
        name = strip_tags(row[0])
        if not name:
            continue
        if is_row_blank_except_name(row):
            cur_type = classify_armor_category(name) or cur_type
            continue
        if not cur_type:
            if not_converted is not None:
                not_converted.append({
                    "name": name, "section_id": None,
                    "reason": "armor table row with no determinable armor category (light/medium/heavy/shield); "
                              "skipped rather than guessing a `type` the schema requires",
                })
            continue
        rec = {"name": name, "source": book_source, "rarity": "none", "type": cur_type}
        if i_cost is not None and i_cost < len(row):
            v, vm, _ok = parse_cost(row[i_cost])
            if v is not None:
                rec["value"] = v
            if vm is not None:
                rec["valueMult"] = vm
        if i_ac is not None and i_ac < len(row):
            m = re.search(r"\d+", strip_tags(row[i_ac]))
            if m:
                rec["ac"] = int(m.group())
        if i_str is not None and i_str < len(row):
            m = re.search(r"\d+", strip_tags(row[i_str]))
            if m:
                rec["strength"] = m.group()
        if i_stealth is not None and i_stealth < len(row) and "disadvantage" in strip_tags(row[i_stealth]).lower():
            rec["stealth"] = True
        if i_weight is not None and i_weight < len(row):
            w, wm, _ok = parse_weight(row[i_weight])
            if w is not None:
                rec["weight"] = w
            if wm is not None:
                rec["weightMult"] = wm
        lead = leadins.get(norm(name))
        if lead:
            rec["entries"] = lead
        out.append(rec)
    return out


def process_simple_table(table, book_source, item_type, leadins, speed_col=True, capacity_col=True):
    """Generic Name+Cost(+Weight|+Speed/Capacity) table -> `item` records with
    `rarity:"none"`. Handles embedded bold category-separator rows (e.g.
    "Arcane focus") by remembering the category name so its members can fall
    back to ITS lead-in text if they have none of their own."""
    labels = [strip_tags(l).strip().lower() for l in (table.get("colLabels") or [])]

    def col(*names):
        return next((labels.index(n) for n in names if n in labels), None)

    i_cost, i_weight = col("cost"), col("weight")
    i_speed = col("speed") if speed_col else None
    i_cap = col("carrying capacity") if capacity_col else None
    out = []
    cur_cat = None
    for row in table.get("rows", []):
        name = strip_tags(row[0])
        if not name:
            continue
        if is_row_blank_except_name(row):
            cur_cat = name
            continue
        rec = {"name": name, "source": book_source, "rarity": "none", "type": item_type}
        if i_cost is not None and i_cost < len(row):
            v, vm, _ok = parse_cost(row[i_cost])
            if v is not None:
                rec["value"] = v
            if vm is not None:
                rec["valueMult"] = vm
        if i_weight is not None and i_weight < len(row):
            w, wm, _ok = parse_weight(row[i_weight])
            if w is not None:
                rec["weight"] = w
            if wm is not None:
                rec["weightMult"] = wm
        if i_speed is not None and i_speed < len(row):
            m = re.search(r"[\d.]+", strip_tags(row[i_speed]))
            if m:
                rec["speed"] = int(float(m.group()))
        if i_cap is not None and i_cap < len(row):
            m = re.search(r"\d+", strip_tags(row[i_cap]).replace(",", ""))
            if m:
                rec["carryingCapacity"] = int(m.group())
        lead = leadins.get(norm(name)) or (leadins.get(norm(cur_cat)) if cur_cat else None)
        if lead:
            rec["entries"] = lead
        out.append(rec)
    return out


TOOL_CATEGORY_TYPE = {"artisan's tools": "AT", "gaming sets": "GS", "musical instruments": "INS"}


def process_tools_table(table, book_source, leadins):
    out = []
    cur_cat_type, cur_cat_name = "T", None
    for row in table.get("rows", []):
        name = strip_tags(row[0])
        if not name:
            continue
        if is_row_blank_except_name(row):
            cur_cat_name = name
            cur_cat_type = TOOL_CATEGORY_TYPE.get(name.lower(), "T")
            continue
        rec = {"name": name, "source": book_source, "rarity": "none", "type": cur_cat_type}
        if len(row) > 1:
            v, vm, _ok = parse_cost(row[1])
            if v is not None:
                rec["value"] = v
            if vm is not None:
                rec["valueMult"] = vm
        if len(row) > 2:
            w, wm, _ok = parse_weight(row[2])
            if w is not None:
                rec["weight"] = w
            if wm is not None:
                rec["weightMult"] = wm
        lead = leadins.get(norm(name)) or (leadins.get(norm(cur_cat_name)) if cur_cat_name else None)
        if lead:
            rec["entries"] = lead
        out.append(rec)
    return out


def process_trade_goods_table(table, book_source):
    """Cost|Goods table where one row's "Goods" text names one or two
    different commodities joined by "or" at the same price point."""
    labels = [strip_tags(l).strip().lower() for l in (table.get("colLabels") or [])]
    i_cost = labels.index("cost") if "cost" in labels else 0
    i_goods = labels.index("goods") if "goods" in labels else 1
    out = []
    seen = set()
    for row in table.get("rows", []):
        if max(i_cost, i_goods) >= len(row):
            continue
        value, _vm, ok = parse_cost(row[i_cost])
        if not ok or value is None:
            continue
        for good in split_trade_good_phrase(strip_tags(row[i_goods])):
            key = norm(good["name"])
            if key in seen:
                continue
            seen.add(key)
            rec = {"name": good["name"], "source": book_source, "rarity": "none", "type": "TG", "value": value}
            if "weight" in good:
                rec["weight"] = good["weight"]
            if "weightNote" in good:
                rec["weightNote"] = good["weightNote"]
            out.append(rec)
    return out


def extract_equipment_chapter(bdata, book_source, not_converted, provenance):
    """PHB/RMR: a full, un-stubbed equipment chapter. Tables are located by
    column signature (robust to RMR splitting PHB's one combined Weapons/
    Armor table into several per-category tables with no separator rows).
    Per-item/-category lead-in prose (the `***Name.*** description`
    paragraphs wave 1 already promoted to named sub-entries) is collected
    once from the whole enclosing chapter, since it can live in a sibling
    sub-heading rather than next to the price table itself (e.g. PHB's
    "Light/Medium/Heavy Armor" blurbs are siblings of the "Armor" table,
    not its children)."""
    baseitems, items = [], []
    pmap = build_parent_map(bdata)

    def record_provenance(coll, rec, nid, match="table"):
        provenance.setdefault(coll, {})[rec["name"]] = {"origin": "markdown", "match": match, "section_id": nid}

    for table, nid, container in all_tables(bdata):
        labels = [strip_tags(l).strip().lower() for l in (table.get("colLabels") or [])]
        caption = (table.get("caption") or "").lower()
        container_name = (container.get("name") or "").lower() if container else ""
        context = caption or container_name

        if "damage" in labels and "properties" in labels:
            chapter = nearest_chapter_ancestor(table, pmap)
            leadins = collect_leadins(chapter)
            for rec in process_weapon_table(table, book_source, nid, leadins, not_converted):
                baseitems.append(rec)
                record_provenance("baseitem", rec, nid)
        elif "armor class (ac)" in labels or "ac" in labels:
            chapter = nearest_chapter_ancestor(table, pmap)
            leadins = collect_leadins(chapter)
            for rec in process_armor_table(table, book_source, leadins, context, not_converted):
                baseitems.append(rec)
                record_provenance("baseitem", rec, nid)
        elif set(labels) == {"item", "cost", "weight"}:
            chapter = nearest_chapter_ancestor(table, pmap)
            leadins = collect_leadins(chapter)
            if "tool" in context:
                for rec in process_tools_table(table, book_source, leadins):
                    items.append(rec)
                    record_provenance("item", rec, nid)
            elif "tack" in context or "harness" in context:
                for rec in process_simple_table(table, book_source, "TAH", leadins, speed_col=False, capacity_col=False):
                    items.append(rec)
                    record_provenance("item", rec, nid)
            else:
                for rec in process_simple_table(table, book_source, "G", leadins, speed_col=False, capacity_col=False):
                    items.append(rec)
                    record_provenance("item", rec, nid)
        elif "speed" in labels and "carrying capacity" in labels:
            for rec in process_simple_table(table, book_source, "MNT", {}):
                items.append(rec)
                record_provenance("item", rec, nid)
        elif "speed" in labels and "carrying capacity" not in labels and "water" in context:
            for rec in process_simple_table(table, book_source, "SHP", {}, speed_col=True, capacity_col=False):
                items.append(rec)
                record_provenance("item", rec, nid)
        elif set(labels) == {"cost", "goods"}:
            for rec in process_trade_goods_table(table, book_source):
                items.append(rec)
                record_provenance("item", rec, nid)
    return baseitems, items


# ---------------------------------------------------------------------------
# 7. Pipeline E: DMG Firearms / Explosives / Poisons (fully present prose)
# ---------------------------------------------------------------------------


def extract_dmg_extras(bdata, book_source, provenance, already_captured):
    items = []

    def record(rec, nid):
        provenance.setdefault("item", {})[rec["name"]] = {"origin": "markdown", "match": "table", "section_id": nid}

    # --- Firearms: 3 tables (Renaissance/Modern/Futuristic), each weapon-shaped ---
    firearms_section = find_by_name(bdata, "Firearms")
    if firearms_section:
        age_order = ["renaissance", "modern", "futuristic"]
        age_idx = 0
        for table, nid, _container in all_tables(firearms_section.get("entries", [])):
            labels = [strip_tags(l).strip().lower() for l in (table.get("colLabels") or [])]
            if "damage" not in labels:
                continue
            age = age_order[age_idx] if age_idx < len(age_order) else None
            age_idx += 1
            for rec in process_weapon_table(table, book_source, nid, {}, []):
                rec["age"] = age
                rec["firearm"] = True
                items.append(rec)
                record(rec, nid)

    # --- Explosives: 2 tables (Renaissance "Bomb/Gunpowder", Modern "Dynamite/Grenades") ---
    explosives_section = find_by_name(bdata, "Explosives")
    if explosives_section:
        leadins = collect_leadins(explosives_section)
        age_order = ["renaissance", "modern"]
        age_idx = 0
        for table, nid, _container in all_tables(explosives_section.get("entries", [])):
            labels = [strip_tags(l).strip().lower() for l in (table.get("colLabels") or [])]
            if "weight" not in labels:
                continue
            age = age_order[age_idx] if age_idx < len(age_order) else None
            age_idx += 1
            for rec in process_simple_table(table, book_source, "EXP|DMG", leadins, speed_col=False, capacity_col=False):
                rec["age"] = age
                items.append(rec)
                record(rec, nid)

    # --- Poisons: Item | Type | Price per Dose ---
    poisons_section = find_by_name(bdata, "Poisons")
    if poisons_section:
        for table, nid, _container in all_tables(poisons_section.get("entries", [])):
            labels = [strip_tags(l).strip().lower() for l in (table.get("colLabels") or [])]
            if "price per dose" not in labels and "type" not in labels:
                continue
            i_type = labels.index("type") if "type" in labels else None
            i_price = labels.index("price per dose") if "price per dose" in labels else None
            for row in table.get("rows", []):
                name = strip_tags(row[0])
                if not name or already_captured(name):
                    continue
                rec = {"name": name, "source": book_source, "rarity": "none", "poison": True}
                if i_type is not None and i_type < len(row):
                    rec["poisonTypes"] = [strip_tags(row[i_type]).strip().lower()]
                if i_price is not None and i_price < len(row):
                    v, _vm, ok = parse_cost(row[i_price])
                    if ok and v is not None:
                        rec["value"] = v
                items.append(rec)
                record(rec, nid)
    return items


# ---------------------------------------------------------------------------
# 8. Pipeline F: SCAG's new (uncosted) musical instruments
# ---------------------------------------------------------------------------

_BOLD_LEAD_RE = re.compile(r"^\{@b\s+([^:{}]+):\}\s*(.*)$")


def extract_scag_instruments(bdata, book_source, provenance):
    section = find_by_name(bdata, "Musical Instruments")
    if not section:
        return []
    out = []
    for node, nid, _container in walk_tree(section.get("entries", [])):
        if node.get("type") != "list":
            continue
        for item_text in node.get("items", []):
            if not isinstance(item_text, str):
                continue
            m = _BOLD_LEAD_RE.match(item_text.strip())
            if not m:
                continue
            rec = {
                "name": m.group(1).strip(), "source": book_source, "rarity": "none",
                "type": "INS", "entries": [m.group(2).strip()],
            }
            out.append(rec)
            provenance.setdefault("baseitem", {})[rec["name"]] = {
                "origin": "markdown", "match": "list", "section_id": nid,
            }
    return out


# ---------------------------------------------------------------------------
# 8b. Pipeline G: final completeness sweep - every remaining same-source
#     official record, however it is cited in this book (even just a single
#     "see the full list online" pointer sentence with no stub/table at all,
#     e.g. XGE's new magic items and instruments).
# ---------------------------------------------------------------------------


def extract_source_complete(book_source, indices, already_captured):
    idx_item, idx_itemgroup, idx_baseitem, idx_mv = indices
    src_norm = norm(book_source)
    found = defaultdict(list)
    for kind, idx in (("item", idx_item), ("itemGroup", idx_itemgroup), ("baseitem", idx_baseitem)):
        for (name, source), rec in idx.items():
            if source != src_norm or already_captured(name):
                continue
            found[kind].append(clean_official_copy(kind, rec, book_source))
    for (name, source), rec in idx_mv.items():
        if source != src_norm or already_captured(name):
            continue
        found["magicvariant"].append(clean_official_copy("magicvariant", rec, book_source))
    return found


# ---------------------------------------------------------------------------
# 9. Driver
# ---------------------------------------------------------------------------


def load_sources():
    doc = json.loads(SOURCES_JSON.read_text(encoding="utf-8"))
    return doc["books"]


def process_book(book_meta, indices):
    src = book_meta["source"]
    book_json_path = BOOKS_JSON_DIR / f"{src}.json"
    if not book_json_path.exists():
        return None
    book_doc = json.loads(book_json_path.read_text(encoding="utf-8"))
    bdata_wrappers = book_doc.get("bookData", [])
    bdata = bdata_wrappers[0]["data"] if bdata_wrappers else []

    provenance = {}
    not_converted = []
    cross_refs = []
    collections = defaultdict(list)

    stub_found = extract_stub_entities(bdata, src, indices, provenance, not_converted)
    for kind, lst in stub_found.items():
        collections[kind].extend(lst)

    captured_variants = set()

    def mark_captured(name):
        captured_variants.update(base_name_variants(norm(name)))

    def already_captured(name):
        return bool(base_name_variants(norm(name)) & captured_variants)

    for kind, lst in collections.items():
        for rec in lst:
            mark_captured(rec["name"])
            if kind == "itemGroup":
                for member in rec.get("items", []):
                    if isinstance(member, str):
                        mark_captured(member.split(",")[0])

    inline_found = extract_inline_items(bdata, src, provenance, already_captured)
    for rec in inline_found:
        mark_captured(rec["name"])
    collections["item"].extend(inline_found)

    table_found = extract_table_mention_entities(
        bdata, src, indices, provenance, cross_refs, not_converted, already_captured, mark_captured
    )
    for kind, lst in table_found.items():
        collections[kind].extend(lst)

    # Book-specific fully-present-prose pipelines.
    if src in ("PHB", "RMR"):
        base_rows, item_rows = extract_equipment_chapter(bdata, src, not_converted, provenance)
        for rec in base_rows + item_rows:
            mark_captured(rec["name"])
        collections["baseitem"].extend(base_rows)
        collections["item"].extend(item_rows)
    if src == "DMG":
        dmg_extra_items = extract_dmg_extras(bdata, src, provenance, already_captured)
        for rec in dmg_extra_items:
            mark_captured(rec["name"])
        collections["item"].extend(dmg_extra_items)
    if src == "SCAG":
        scag_instruments = extract_scag_instruments(bdata, src, provenance)
        for rec in scag_instruments:
            mark_captured(rec["name"])
        collections["baseitem"].extend(scag_instruments)

    # Final completeness sweep (every book): pick up any remaining official
    # record whose own source is this book but that nothing above found any
    # trace of in the markdown at all (not even a stub) - e.g. XGE's new
    # magic items/instruments, which the scraped chapter text only refers to
    # with a single "see the Items page" pointer sentence.
    complete_found = extract_source_complete(src, indices, already_captured)
    for kind, lst in complete_found.items():
        for rec in lst:
            mark_captured(rec["name"])
            provenance.setdefault(kind, {})[rec["name"]] = {"origin": "5etools-src", "match": "source-complete"}
        collections[kind].extend(lst)

    if not any(collections.values()):
        return None

    shard = {
        "_meta": {
            "sources": book_doc["_meta"]["sources"],
            "edition": book_doc["_meta"].get("edition", "classic"),
            "dateAdded": GEN_TIME,
            "dateLastModified": GEN_TIME,
        }
    }
    for kind in ("item", "baseitem", "magicvariant", "itemGroup"):
        if collections.get(kind):
            # de-duplicate by name (a name can only legitimately appear once
            # per top-level array within one book/source).
            seen = {}
            for rec in collections[kind]:
                seen.setdefault(rec["name"], rec)
            shard[kind] = list(seen.values())

    sidecar = {"entities": provenance, "crossReferences": cross_refs, "notConverted": not_converted}
    return shard, sidecar


def main():
    SHARD_DIR.mkdir(parents=True, exist_ok=True)
    indices = load_official_indices()
    books = load_sources()

    report = {"books": {}, "totals": defaultdict(int), "origin_totals": defaultdict(int)}

    for book_meta in books:
        result = process_book(book_meta, indices)
        src = book_meta["source"]
        if not result:
            continue
        shard, sidecar = result
        (SHARD_DIR / f"{src}.json").write_text(json.dumps(shard, indent="\t", ensure_ascii=False) + "\n", encoding="utf-8")
        (SHARD_DIR / f"{src}.provenance.json").write_text(
            json.dumps(sidecar, indent="\t", ensure_ascii=False) + "\n", encoding="utf-8"
        )
        counts = {k: len(shard[k]) for k in ("item", "baseitem", "magicvariant", "itemGroup") if k in shard}
        source_complete_count = sum(
            1 for kind_map in sidecar["entities"].values() for p in kind_map.values() if p["match"] == "source-complete"
        )
        report["books"][src] = {
            "counts": counts,
            "notConverted": len(sidecar["notConverted"]),
            "crossReferences": len(sidecar["crossReferences"]),
            "sourceCompleteCount": source_complete_count,
        }
        for k, v in counts.items():
            report["totals"][k] += v
        for kind_map in sidecar["entities"].values():
            for prov in kind_map.values():
                report["origin_totals"][f"{prov['origin']}:{prov['match']}"] += 1

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
