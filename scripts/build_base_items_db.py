#!/usr/bin/env python3
"""
Build data/base_items.db — mundane "base item" templates (weapons, armour,
shields, ammunition, foci, tools, gear) that crafting materials can be
applied to.

Sources (read-only, never modified):
  ref/homebrew/baseitem/*.json   -> every entry under the top-level "baseitem"
                                     key, origin = 'baseitem'
  ref/homebrew/item/*.json       -> "baseitem" entries (origin='baseitem') and
                                     "item" entries with rarity none/absent
                                     whose type is a craftable mundane
                                     category (origin='mundane item')
  ref/homebrew/collection/*.json -> same two passes as item/*.json

magicvariant/*.json is intentionally excluded: those are magical variant
templates (e.g. "+1 Weapon"), not mundane base items.

Effect/rule text is NEVER copied from `entries` (the source text belongs to
other authors and this repo is public). All descriptive columns are derived
only from *structured* fields (type, property, dmgType, ammoType, mastery,
reload, firearm, focus, resist/immune/vulnerable, packContents, etc).

Usage: python3 scripts/build_base_items_db.py
"""
import json
import os
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOMEBREW_ROOT = REPO_ROOT / "ref" / "homebrew"
DB_PATH = REPO_ROOT / "data" / "base_items.db"

# --------------------------------------------------------------------------
# Reference dictionaries (from 5etools-src data/items-base.json, the
# authoritative itemType/itemProperty tables; fetched 2026-10-12).
# --------------------------------------------------------------------------

ITEM_TYPE_NAMES = {
    "$": "Treasure", "$A": "Treasure (Art Object)", "$C": "Treasure (Coinage)",
    "$G": "Treasure (Gemstone)", "A": "Ammunition", "AF": "Ammunition (Firearm)",
    "AIR": "Vehicle (Air)", "AT": "Artisan's Tools", "EXP": "Explosive",
    "FD": "Food and Drink", "G": "Adventuring Gear", "GS": "Gaming Set",
    "GV": "Generic Variant", "HA": "Heavy Armor", "INS": "Instrument",
    "LA": "Light Armor", "M": "Melee Weapon", "MA": "Medium Armor",
    "MNT": "Mount", "OTH": "Other", "P": "Potion", "R": "Ranged Weapon",
    "RD": "Rod", "RG": "Ring", "S": "Shield", "SC": "Scroll",
    "SCF": "Spellcasting Focus", "SHP": "Vehicle (Water)",
    "SPC": "Vehicle (Space)", "ST": "Staff", "T": "Tool",
    "TAH": "Tack and Harness", "TB": "Trade Bar", "TG": "Trade Good",
    "VEH": "Vehicle (Land)", "WD": "Wand",
}

ITEM_PROPERTY_NAMES = {
    "2H": "Two-Handed", "A": "Ammunition", "AF": "Ammunition (Firearm)",
    "BF": "Burst Fire", "Evo": "Evolving Item", "F": "Finesse", "H": "Heavy",
    "L": "Light", "LD": "Loading", "R": "Reach", "RLD": "Reload",
    "S": "Special", "T": "Thrown", "V": "Versatile",
    "Vst": "Vestige of Divergence",
}

DMG_TYPE_NAMES = {
    "A": "acid", "B": "bludgeoning", "C": "cold", "F": "fire", "O": "force",
    "L": "lightning", "N": "necrotic", "P": "piercing", "I": "poison",
    "Y": "psychic", "R": "radiant", "S": "slashing", "T": "thunder",
}

# type code -> (category, origin-agnostic). Only used to decide whether a
# mundane `item` entry qualifies, and to fill the `category` column.
CATEGORY_MAP = {
    "M": "weapon", "R": "weapon",
    "LA": "armor", "MA": "armor", "HA": "armor",
    "S": "shield",
    "A": "ammunition", "AF": "ammunition",
    "RD": "focus", "ST": "focus", "WD": "focus", "SCF": "focus",
    "AT": "tool", "INS": "tool", "GS": "tool", "T": "tool", "TAH": "tool",
    "G": "gear",
}
# The set of types a mundane `item` entry must have to be included.
MUNDANE_ALLOWED_TYPES = set(CATEGORY_MAP.keys())

VALID_RARITIES = {
    "none", "common", "uncommon", "rare", "very rare", "legendary",
    "artifact", "varies", "unknown",
}

TAG_RE = re.compile(r"\{@\w+ ([^}|]+)(?:\|[^}]*)?\}")


def detag(s):
    """Strip 5etools {@tag text|...} markup down to plain text (used only on
    short structured labels like ammoType, never on narrative `entries`)."""
    if not isinstance(s, str):
        return s
    return TAG_RE.sub(r"\1", s)


def strip_source_suffix(code):
    if not isinstance(code, str):
        return code
    return code.split("|", 1)[0]


def normalize_rarity(r):
    if r is None or r == "":
        return "none"
    r = str(r).strip().lower()
    if r == "unknown (magic)":
        return "unknown"
    if r in VALID_RARITIES:
        return r
    return "unknown"


def load_local_dict(file_data, key, names_field="abbreviation"):
    """Read a file-local itemProperty/itemType array (if present) and return
    an {abbreviation: name} dict, resolving name from either an explicit
    'name' key or the first nested entries[0].name."""
    out = {}
    arr = file_data.get(key)
    if not isinstance(arr, list):
        return out
    for entry in arr:
        if not isinstance(entry, dict):
            continue
        ab = entry.get(names_field)
        if not ab or ab in out:
            continue
        name = entry.get("name")
        if not name:
            entries = entry.get("entries")
            if isinstance(entries, list) and entries:
                first = entries[0]
                if isinstance(first, dict):
                    name = first.get("name")
        if name:
            out[ab] = name
    return out


def build_source_lookup(meta):
    """Map both the 'json' and 'abbreviation' keys of each _meta.sources[]
    entry to that entry, since homebrew item.source values are observed to
    match either one depending on the brew."""
    lookup = {}
    sources = (meta or {}).get("sources") or []
    for s in sources:
        if not isinstance(s, dict):
            continue
        for key in (s.get("json"), s.get("abbreviation")):
            if key:
                lookup[key] = s
    return lookup, sources


def resolve_source(item_source, src_lookup, all_sources):
    src = src_lookup.get(item_source)
    if src is None and len(all_sources) == 1:
        src = all_sources[0]
    if src is None:
        return None, None, None, None
    abbrev = src.get("abbreviation")
    full = src.get("full")
    authors = src.get("authors") or []
    authors_str = ", ".join(a for a in authors if isinstance(a, str)) or None
    url = src.get("url")
    return abbrev, full, authors_str, url


# --------------------------------------------------------------------------
# Material-hint heuristic (name/type keyword based — approximate by design;
# documented as a known gap in the final report).
# --------------------------------------------------------------------------

_MATERIAL_KEYWORDS = [
    # (material, [substrings to match against lowercased item name])
    ("leather", ["leather", "hide armor", "buff coat", "whip", "scourge",
                 "sling", "quiver", "saddle", "harness", "satchel",
                 "scabbard", "holster", "bolas", "garrote"]),
    ("cloth", ["padded", "gambeson", "robe", "cloak", "silk", "quilted",
               "vestment", "cloth"]),
    ("bone", ["bone", "antler", "fang", "tusk", "horn", "ivory", "skull",
              "chitin", "shell"]),
    ("stone", ["stone", "granite", "obsidian", "flint", "slate"]),
    ("metal", ["sword", "blade", "axe", "mace", "hammer", "pick", "flail",
               "chainmail", "chain mail", "chain shirt", "plate", "splint",
               "banded", "scale mail", "halberd", "glaive", "pike", "rapier",
               "sabre", "saber", "scimitar", "trident", "dagger", "knife",
               "gun", "pistol", "rifle", "firearm", "bullet", "shot", "ring",
               "rod", "buckler", "cutlass", "gauntlet", "shears", "needle",
               "pin", "wire", "katana", "tanto", "wakizashi", "naginata",
               "claymore", "falchion", "gladius", "kukri", "chakram",
               "cestus", "knuckles", "bayonet", "harpoon", "kama",
               "musket", "carbine", "blunderbuss", "arquebus", "musketoon",
               "matchlock", "cannon", "revolver", "repeater", "phaser",
               "laser", "flamethrower", "scythe", "urgrosh", "kris",
               "estoc", "longsword", "shortsword", "broadsword",
               "cartridge", "round", "slug", "energy cell"]),
    ("wood", ["bow", "staff", "quarterstaff", "club", "blowgun", "spear",
              "javelin", "lance", "arrow", "bolt", "wand", "shield",
              "crossbow", "sling staff", "cudgel", "pole", "tonfa",
              "nunchaku", "bo stick", "ballista", "catapult", "trebuchet"]),
]


def guess_material(name, category, item_type_code):
    low = (name or "").lower()
    for material, keywords in _MATERIAL_KEYWORDS:
        for kw in keywords:
            if kw in low:
                return material
    # Category-level fallback defaults.
    if category == "armor":
        if item_type_code == "LA":
            return "leather"
        return "metal"
    if category == "shield":
        return "wood"
    if category == "ammunition":
        return "wood"
    if category == "focus":
        if item_type_code in ("RD", "WD", "ST"):
            return "wood"
        return "unknown"
    if category == "tool":
        return "other"
    if category == "gear":
        return "other"
    return "unknown"


# --------------------------------------------------------------------------
# Notes builder — structured-field only, never touches narrative `entries`.
# --------------------------------------------------------------------------

def build_notes(it, props_local):
    clauses = []
    if it.get("firearm") is True:
        clauses.append("firearm")
    age = it.get("age")
    if isinstance(age, str) and age.lower() == "futuristic":
        clauses.append("futuristic")
    reload_ = it.get("reload")
    if isinstance(reload_, (int, float)):
        clauses.append(f"reload {int(reload_)} shots")
    ammo_type = it.get("ammoType")
    if isinstance(ammo_type, str):
        at = detag(strip_source_suffix(ammo_type)).strip()
        if at:
            clauses.append(f"uses {at} ammo")
    mastery = it.get("mastery")
    if isinstance(mastery, list) and mastery:
        names = [strip_source_suffix(m) for m in mastery if isinstance(m, str)]
        if names:
            clauses.append("mastery: " + ", ".join(names))
    focus = it.get("focus")
    if isinstance(focus, list) and focus:
        names = [strip_source_suffix(f) for f in focus if isinstance(f, str)]
        if names:
            clauses.append("focus for: " + ", ".join(n.title() for n in names))
    elif focus is True:
        clauses.append("spellcasting focus")
    for field, label in (("resist", "resists"), ("immune", "immune to"),
                          ("vulnerable", "vulnerable to"),
                          ("conditionImmune", "immune to condition")):
        val = it.get(field)
        if isinstance(val, list) and val:
            vals = [v for v in val if isinstance(v, str)]
            if vals:
                clauses.append(f"{label} {', '.join(vals)}")
    pack = it.get("packContents")
    if isinstance(pack, list) and pack:
        clauses.append(f"pack of {len(pack)} component item(s)")
    if it.get("poison") is True:
        clauses.append("poisoned")
    if it.get("curse") is True:
        clauses.append("cursed")
    if not clauses and it.get("entries"):
        # Has narrative rule text we deliberately don't reproduce.
        clauses.append("additional rules in source text")
    return "; ".join(clauses) if clauses else None


def build_properties_str(it, props_local):
    prop = it.get("property")
    if not isinstance(prop, list):
        return None
    names = []
    for p in prop:
        if not isinstance(p, str):
            continue
        code = strip_source_suffix(p)
        name = props_local.get(code) or ITEM_PROPERTY_NAMES.get(code) or code
        names.append(name)
    return ", ".join(names) if names else None


def build_damage_str(it):
    dmg1 = it.get("dmg1")
    if not dmg1:
        return None
    dmg_type_code = strip_source_suffix(it.get("dmgType")) if it.get("dmgType") else None
    dmg_type_name = DMG_TYPE_NAMES.get(dmg_type_code) if dmg_type_code else None
    s = dmg1
    if dmg_type_name:
        s += f" {dmg_type_name}"
    dmg2 = it.get("dmg2")
    prop_codes = {strip_source_suffix(p) for p in it.get("property", []) if isinstance(p, str)}
    if dmg2 and "V" in prop_codes:
        s += f" (versatile {dmg2})"
    return s


def to_number(v):
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        m = re.search(r"-?\d+(\.\d+)?", v)
        if m:
            return float(m.group())
    return None


def to_int(v):
    n = to_number(v)
    return int(n) if n is not None else None


# --------------------------------------------------------------------------
# Row extraction
# --------------------------------------------------------------------------

def make_row(it, origin, source_abbrev, book, page, brew_file,
             source_book_abbrev, source_book_full, source_book_authors,
             source_book_url, types_local, props_local):
    name = it.get("name")
    raw_type = it.get("type")
    type_code = strip_source_suffix(raw_type) if raw_type else None
    type_name = None
    if type_code:
        type_name = types_local.get(type_code) or ITEM_TYPE_NAMES.get(type_code)
    category = CATEGORY_MAP.get(type_code, "other")

    weapon_category = it.get("weaponCategory")
    if isinstance(weapon_category, str):
        weapon_category = weapon_category.strip()
    else:
        weapon_category = None

    dmg1 = it.get("dmg1")
    dmg2 = it.get("dmg2")
    dmg_type_code = strip_source_suffix(it.get("dmgType")) if it.get("dmgType") else None
    dmg_type_name = DMG_TYPE_NAMES.get(dmg_type_code) if dmg_type_code else None

    weight = to_number(it.get("weight"))
    value_cp = to_number(it.get("value"))
    value_gp = (value_cp / 100.0) if value_cp is not None else None

    ac = to_int(it.get("ac"))
    strength_req = to_int(it.get("strength"))
    stealth = it.get("stealth")
    stealth_disadvantage = 1 if stealth is True else (0 if stealth is False else None)

    rng = it.get("range") if isinstance(it.get("range"), str) else None

    row = {
        "item_name": name,
        "source_abbrev": source_abbrev,
        "book": book,
        "page": to_int(page) if page is not None else None,
        "brew_file": brew_file,
        "origin": origin,
        "item_type_code": type_code,
        "item_type_name": type_name,
        "category": category,
        "weapon_category": weapon_category,
        "dmg1": dmg1,
        "dmg2": dmg2,
        "dmg_type_code": dmg_type_code,
        "dmg_type_name": dmg_type_name,
        "damage": build_damage_str(it),
        "properties": build_properties_str(it, props_local),
        "range": rng,
        "ac": ac,
        "strength_req": strength_req,
        "stealth_disadvantage": stealth_disadvantage,
        "weight": weight,
        "value_gp": value_gp,
        "primary_material_hint": guess_material(name, category, type_code),
        "notes": build_notes(it, props_local),
        "source_book_abbrev": source_book_abbrev,
        "source_book_full": source_book_full,
        "source_book_authors": source_book_authors,
        "source_book_url": source_book_url,
    }
    return row


def iter_source_files():
    for sub in ("baseitem", "item", "collection"):
        d = HOMEBREW_ROOT / sub
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.json")):
            yield sub, f


def process_file(sub, path, seen, rows, stats):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        stats["load_errors"].append((str(path), str(e)))
        return

    brew_file = str(path.relative_to(HOMEBREW_ROOT))
    meta = data.get("_meta") or {}
    src_lookup, all_sources = build_source_lookup(meta)
    types_local = dict(ITEM_TYPE_NAMES)
    types_local.update(load_local_dict(data, "itemType"))
    props_local = dict(ITEM_PROPERTY_NAMES)
    props_local.update(load_local_dict(data, "itemProperty"))

    def add(it, origin):
        name = it.get("name")
        source = it.get("source")
        if not name or not source:
            stats["skipped_no_name_source"] += 1
            return
        key = (name.strip().lower(), source)
        if key in seen:
            stats["dedup_skipped"] += 1
            return
        seen.add(key)
        abbrev, full, authors, url = resolve_source(source, src_lookup, all_sources)
        row = make_row(
            it, origin, source, full, it.get("page"), brew_file,
            abbrev, full, authors, url, types_local, props_local,
        )
        rows.append(row)
        stats["origin_count"][origin] += 1
        stats["category_count"][row["category"]] += 1

    # Pass: baseitem key -> ALL entries, unconditionally.
    for it in data.get("baseitem") or []:
        if isinstance(it, dict):
            add(it, "baseitem")

    # Pass: item key -> only rarity none/absent + allowed craftable type.
    for it in data.get("item") or []:
        if not isinstance(it, dict):
            continue
        rarity_raw = it.get("rarity")
        is_mundane_rarity = rarity_raw is None or str(rarity_raw).strip().lower() in ("", "none")
        if not is_mundane_rarity:
            continue
        raw_type = it.get("type")
        type_code = strip_source_suffix(raw_type) if raw_type else None
        if type_code not in MUNDANE_ALLOWED_TYPES:
            continue
        add(it, "mundane item")


def main():
    rows = []
    seen = set()
    stats = {
        "load_errors": [],
        "skipped_no_name_source": 0,
        "dedup_skipped": 0,
        "origin_count": {"baseitem": 0, "mundane item": 0},
        "category_count": defaultdict(int),
    }

    for sub, path in iter_source_files():
        process_file(sub, path, seen, rows, stats)

    # Normalize rarity is not stored (base items are mundane templates), but
    # we still want item_type_name/category populated for every row, and
    # rarity-bearing rows (e.g. baseitem entries that happen to carry a
    # rarity like RD/WD templates) shouldn't crash — we simply don't store
    # rarity on this table at all, matching the "mundane template" scope.

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE base_items (
            id INTEGER PRIMARY KEY,
            item_name TEXT NOT NULL,
            source_abbrev TEXT NOT NULL,
            book TEXT,
            page INTEGER,
            brew_file TEXT NOT NULL,
            origin TEXT NOT NULL CHECK (origin IN ('baseitem', 'mundane item')),
            item_type_code TEXT,
            item_type_name TEXT,
            category TEXT,
            weapon_category TEXT,
            dmg1 TEXT,
            dmg2 TEXT,
            dmg_type_code TEXT,
            dmg_type_name TEXT,
            damage TEXT,
            properties TEXT,
            range TEXT,
            ac INTEGER,
            strength_req INTEGER,
            stealth_disadvantage INTEGER,
            weight REAL,
            value_gp REAL,
            primary_material_hint TEXT,
            notes TEXT,
            source_book_abbrev TEXT,
            source_book_full TEXT,
            source_book_authors TEXT,
            source_book_url TEXT,
            UNIQUE(item_name, source_abbrev)
        )
    """)
    conn.execute("CREATE INDEX idx_base_items_category ON base_items(category)")
    conn.execute("CREATE INDEX idx_base_items_type ON base_items(item_type_code)")
    conn.execute("CREATE INDEX idx_base_items_origin ON base_items(origin)")
    conn.execute("CREATE INDEX idx_base_items_material ON base_items(primary_material_hint)")

    cols = [
        "item_name", "source_abbrev", "book", "page", "brew_file", "origin",
        "item_type_code", "item_type_name", "category", "weapon_category",
        "dmg1", "dmg2", "dmg_type_code", "dmg_type_name", "damage",
        "properties", "range", "ac", "strength_req", "stealth_disadvantage",
        "weight", "value_gp", "primary_material_hint", "notes",
        "source_book_abbrev", "source_book_full", "source_book_authors",
        "source_book_url",
    ]
    placeholders = ", ".join("?" for _ in cols)
    conn.executemany(
        f"INSERT INTO base_items ({', '.join(cols)}) VALUES ({placeholders})",
        [tuple(r[c] for c in cols) for r in rows],
    )
    conn.commit()

    print(f"Wrote {len(rows)} rows to {DB_PATH}")
    print(f"By origin: {stats['origin_count']}")
    print(f"By category: {stats['category_count']}")
    print(f"Dedup-skipped duplicates: {stats['dedup_skipped']}")
    print(f"Skipped (no name/source): {stats['skipped_no_name_source']}")
    if stats["load_errors"]:
        print(f"Load errors ({len(stats['load_errors'])}):")
        for f, e in stats["load_errors"][:10]:
            print(f"  {f}: {e}")
    conn.close()


if __name__ == "__main__":
    sys.exit(main())
