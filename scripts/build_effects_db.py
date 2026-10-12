#!/usr/bin/env python3
"""Build data/effects.db: a deduplicated reference database of mechanical
effects found on D&D 5e homebrew items (TheGiddyLimit/homebrew mirror),
plus the user's own crafting-material handouts, classified with a shared
taxonomy so the two can be compared.

Reads (read-only):
  ref/homebrew/collection/*.json
  ref/homebrew/item/*.json
  ref/homebrew/baseitem/*.json
  ref/homebrew/magicvariant/*.json
  Hides-and-leather.md, ores-and-ingots.md, woods-and-branches.md (repo root)

Writes:
  data/effects.db

Re-runnable: drops and rebuilds the output database each time.

------------------------------------------------------------------------
Design notes / known heuristics (see also the final build report):

* Atomisation order follows the assignment: structured item fields first
  (resist/immune/vulnerable/conditionImmune/modifySpeed/bonus*/charges/
  recharge/...), then 5etools {@tag} markup (converted to plain text),
  then keyword/regex heuristics over the remaining prose. Tags are
  converted to plain text BEFORE the prose heuristics run, so steps 2
  and 3 share one regex pass; this is equivalent in practice because a
  tag-derived number/word (e.g. "{@dice 1d8}" -> "1d8") is indistinguishable
  from the same text written directly as prose.
* All classification tables (damage types, conditions, item type codes,
  regexes, category defaults) are plain Python data structures near the
  top of the file so they are easy to extend without touching the
  pipeline logic.
* `effect` rows are keyed on (category, subtype, trigger) only -- NOT on
  magnitude -- so e.g. every "+1d6 fire damage on hit" item collapses
  into one `damage rider`/`fire`/`on hit` pattern row, with the full
  spread of magnitudes kept in `magnitude_values`/`magnitude_summary`.
* `effect_occurrence.summary` is always synthesised from the classified
  fields (category/subtype/trigger/magnitude/uses), never sliced from the
  source text, so it can never be a verbatim copy of someone else's
  homebrew prose.
* Known gaps (heuristic, may misclassify or under/over-count -- see the
  printed build report for the live numbers):
    - `property` (weapon property) codes are not expanded into effects.
      Homebrew authors invent hundreds of one-off property codes with
      their own rule text in a separate `itemProperty` table; resolving
      those and attaching their rules to every item that carries the
      property was judged out of scope next to the item's own `entries`.
    - `dmgType` (a weapon's own base damage type) is never turned into an
      atom by itself -- only *additional/explicit* damage mentioned in
      `entries` or in bonus* fields counts as an effect. This avoids
      treating every mundane sword's "slashing" as a magical rider.
    - 5etools "generic variant" magicvariant/_copy templating
      (`{#itemEntry ...}` placeholders, full `_copy`/`_mod` JSON-patch
      resolution, `inherits` chains against other homebrew or core-book
      base items) is not fully resolved. We read top-level fields with a
      fallback to `inherits.*`, and pull any literal strings appended via
      `_copy._mod.*entries*`, but do not reconstruct the final rendered
      item the way the 5etools site does. Affects ~10 items in
      magicvariant/*.json plus a modest number of generic-variant entries
      embedded in collection/*.json.
    - Items that are pure `_copy` reprints of a core-book item with no
      entries of their own (e.g. a compendium re-listing "Abacus" from
      the PHB) will show zero atoms, because the real PHB text they copy
      is not present in this homebrew-only checkout.
    - Prose regexes are necessarily approximate free-text heuristics:
      trigger inference (on hit / on crit / area / passive / reaction)
      uses local keyword windows and can mis-tag unusual phrasing;
      "uses" frequency falls back to the item's structured
      charges/recharge when no "once per ..." phrase is found nearby,
      and to the literal string "unknown" when neither is available.
    - dmgType single-letter -> damage-word mapping (used nowhere in the
      final atoms, kept only as documentation) was inferred empirically
      from co-occurring words in this corpus, not from an official table.
------------------------------------------------------------------------
"""

import glob
import json
import os
import re
import sqlite3
import sys
from collections import Counter, namedtuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOMEBREW_ROOT = os.path.join(REPO_ROOT, "ref", "homebrew")
DATA_DIR = os.path.join(REPO_ROOT, "data")
DB_PATH = os.path.join(DATA_DIR, "effects.db")

ITEM_ARRAY_KEYS = ("item", "baseitem", "magicvariant", "itemGroup")

# Directories scanned, in dedup-priority order: a (name, source) pair seen
# in an earlier directory wins over the same pair seen later (collection/
# mirrors item/baseitem/magicvariant, so those take priority).
SCAN_DIRS = ["item", "baseitem", "magicvariant", "collection"]


# ===========================================================================
# Static taxonomy / vocabulary tables (data-driven, extend freely)
# ===========================================================================

DAMAGE_TYPES = [
    "acid", "bludgeoning", "cold", "fire", "force", "lightning", "necrotic",
    "piercing", "poison", "psychic", "radiant", "slashing", "thunder",
]
DAMAGE_TYPES_SET = set(DAMAGE_TYPES)
DMG_PAT = r"(" + "|".join(DAMAGE_TYPES) + r")"
DICE_PAT = r"\d+d\d+(?:\s*[+-]\s*\d+)?|\d+"

# Inferred empirically (see module docstring) -- NOT used to build atoms,
# kept only for documentation of the item `dmgType` field's vocabulary.
DMG_TYPE_CODE_MAP = {
    "A": "acid", "B": "bludgeoning", "C": "cold", "F": "fire", "I": "poison",
    "L": "lightning", "N": "necrotic", "O": "force", "P": "piercing",
    "R": "radiant", "S": "slashing", "T": "thunder", "Y": "psychic",
}

CONDITIONS = [
    "blinded", "charmed", "deafened", "exhaustion", "frightened", "grappled",
    "incapacitated", "invisible", "paralyzed", "petrified", "poisoned",
    "prone", "restrained", "stunned", "unconscious",
]
COND_PAT = "(" + "|".join(CONDITIONS) + ")"
COND_NC = "(?:" + "|".join(CONDITIONS) + ")"
CONDITION_ALIASES = {
    "paralysed": "paralyzed",
    "frigthened": "frightened",
    "lesser poisoned": "poisoned (lesser)",
}

RARITY_ALLOWED = {
    "none", "common", "uncommon", "rare", "very rare", "legendary",
    "artifact", "varies", "unknown",
}

ABILS = {"str": "Strength", "dex": "Dexterity", "con": "Constitution",
          "int": "Intelligence", "wis": "Wisdom", "cha": "Charisma"}

# Official/common 5etools item type codes -> friendly label. Anything not
# in this table is resolved via each brew's own `itemType` definitions
# (collected into CUSTOM_TYPE_NAMES), else kept as the raw code.
STANDARD_ITEM_TYPES = {
    "M": "Melee Weapon", "R": "Ranged Weapon", "A": "Ammunition",
    "LA": "Light Armor", "MA": "Medium Armor", "HA": "Heavy Armor", "S": "Shield",
    "RD": "Rod", "ST": "Staff", "WD": "Wand", "SCF": "Spellcasting Focus",
    "RG": "Ring", "P": "Potion", "SC": "Scroll", "G": "Adventuring Gear",
    "T": "Tool", "AT": "Artisan's Tools", "INS": "Musical Instrument",
    "GS": "Gaming Set", "TAH": "Tack and Harness", "TG": "Trade Good",
    "VEH": "Vehicle (Land)", "SHP": "Vehicle (Water)", "AIR": "Vehicle (Air)",
    "MNT": "Mount", "EXP": "Explosive", "OTH": "Other",
    "GV": "Generic Variant", "FD": "Food and Drink",
}

# Categories whose atoms are "always on" while the item is worn/held/
# attuned; these default to uses='always' unless a more specific uses
# string was captured from local context.
PASSIVE_CATEGORIES = {
    "resistance", "immunity", "vulnerability", "condition immunity",
    "AC bonus", "attack bonus", "weapon bonus", "damage bonus",
    "saving throw bonus", "spell save dc bonus", "spell damage bonus",
    "ability check bonus", "ability score bonus", "advantage", "disadvantage",
    "movement speed", "light/vision", "stealth", "sentience", "curse",
    "utility",
}
# Categories that default to "at will" (always triggers, no cost) rather
# than inheriting the item's charge economy, because that's the dominant
# real-world convention for on-hit weapon riders.
AT_WILL_DEFAULT_CATEGORIES = {"damage rider"}

RECHARGE_LABELS = {
    "dawn": "dawn", "dusk": "dusk", "midnight": "midnight",
    "restLong": "long rest", "restShort": "short or long rest",
    "decade": "decade", "week": "week", "month": "month",
    "round": "each round", "special": "special (see text)",
}

PER_PHRASE_RE = re.compile(
    r"once per (?:turn|round|short or long rest|long rest|short rest|day|dawn|dusk)"
    r"|\d+\s+times?\s+per\s+(?:turn|round|short or long rest|long rest|short rest|day)",
    re.I,
)

Atom = namedtuple("Atom", ["category", "subtype", "trigger", "magnitude", "uses"])


# ===========================================================================
# Generic JSON text helpers
# ===========================================================================

def flatten_text(node, out=None):
    """Recursively collect every string leaf in a 5etools entries blob."""
    if out is None:
        out = []
    if isinstance(node, str):
        out.append(node)
    elif isinstance(node, list):
        for x in node:
            flatten_text(x, out)
    elif isinstance(node, dict):
        for v in node.values():
            flatten_text(v, out)
    return out


_TAG_RE = re.compile(r"\{@(\w+)([^{}]*)\}")


def _tag_repl(m):
    tag = m.group(1)
    body = m.group(2).strip()
    if not body:
        return ""
    parts = [p.strip() for p in body.split("|")]
    first = parts[0]
    last = parts[-1] if parts else ""
    if tag == "dc":
        return f"DC {first}"
    if tag == "hit":
        return first if first.startswith(("+", "-")) else f"+{first}"
    if tag == "chance":
        return f"{first}%"
    if tag == "recharge":
        return f"(Recharge {first or '6'}-6)"
    if len(parts) > 1 and last and (" " in last or len(last) > 15):
        return last
    return first


def strip_tags(text):
    """Render 5etools {@tag ...} markup as plain text."""
    if not text:
        return ""
    out = text
    prev = None
    for _ in range(3):
        if out == prev:
            break
        prev = out
        out = _TAG_RE.sub(_tag_repl, out)
    out = re.sub(r"\{[#=][^{}]*\}", "", out)  # leftover templating directives
    out = re.sub(r"[{}]", "", out)
    out = re.sub(r"\s+", " ", out).strip()
    return out

_PAREN_DICE_RE = re.compile(r"\d+\s*\((\d+d\d+(?:\s*[+-]\s*\d+)?)\)")


def collapse_parenthetical_dice(text):
    """"10 (3d6) fire damage" -> "3d6 fire damage": published-book style
    text gives the rounded average before the real dice in parentheses;
    prefer the dice expression so our dice-pattern regexes still match."""
    return _PAREN_DICE_RE.sub(r"\1", text)


def extract_mod_entries_text(copy_obj):
    """Pull literal appended prose out of a `_copy._mod.*entries*` patch."""
    out = []
    if not isinstance(copy_obj, dict):
        return out
    mod = copy_obj.get("_mod")
    if not isinstance(mod, dict):
        return out
    for path_key, changes in mod.items():
        if "entries" not in path_key:
            continue
        change_list = changes if isinstance(changes, list) else [changes]
        for ch in change_list:
            if not isinstance(ch, dict):
                continue
            val = ch.get("items", ch.get("value"))
            if isinstance(val, str):
                out.append(val)
            elif isinstance(val, list):
                out.extend(x for x in val if isinstance(x, str))
    return out


def window_before(text, pos, maxlen=140):
    chunk = text[max(0, pos - maxlen):pos]
    bounds = list(re.finditer(r"[.!?]\s+", chunk))
    if bounds:
        chunk = chunk[bounds[-1].end():]
    return chunk


def window_after(text, pos, maxlen=140):
    chunk = text[pos:pos + maxlen]
    m = re.search(r"[.!?]\s", chunk)
    if m:
        chunk = chunk[:m.end()]
    return chunk


def has_any(s, words):
    sl = s.lower()
    return any(w in sl for w in words)


def crit_nearby(text, pos, maxlen=260):
    """Critical-hit context is often established one sentence earlier than
    the bonus-damage/effect sentence that depends on it ("When you score a
    critical hit, X happens. The target also takes an additional Ndm
    damage."), so this check intentionally is NOT bounded to the current
    sentence the way `window_before` is."""
    return has_any(text[max(0, pos - maxlen):pos], ["critical hit", " crit "])


def local_uses(text, start, end, window=260):
    seg = text[max(0, start - window):min(len(text), end + 40)]
    m = PER_PHRASE_RE.search(seg)
    return m.group(0).lower() if m else None


# ===========================================================================
# Normalisers
# ===========================================================================

def normalize_rarity(raw):
    if not isinstance(raw, str) or not raw.strip():
        return "unknown"
    r = raw.strip().lower()
    if r in RARITY_ALLOWED:
        return r
    if r.startswith("unknown"):
        return "unknown"
    if r.replace("  ", " ") in RARITY_ALLOWED:
        return r.replace("  ", " ")
    return "unknown"


def normalize_page(page):
    if page is None:
        return None
    if isinstance(page, int):
        return page
    if isinstance(page, str):
        m = re.search(r"\d+", page)
        return int(m.group(0)) if m else page
    return page


def resolve_item_type(raw_type, item_source, custom_type_names):
    """Returns a single display string for the item's `type` code."""
    if isinstance(raw_type, str) and raw_type.strip():
        base, _, suffix_src = raw_type.partition("|")
        base = base.strip()
        if base in STANDARD_ITEM_TYPES:
            return STANDARD_ITEM_TYPES[base]
        if base.startswith("$"):
            return "Treasure"
        for src_try in filter(None, [suffix_src or None, item_source]):
            name = custom_type_names.get((base, src_try))
            if name:
                return name
        candidates = {v for (b, _s), v in custom_type_names.items() if b == base}
        if len(candidates) == 1:
            return next(iter(candidates))
        return base
    return None


def format_uses(charges, recharge, recharge_amount):
    if charges is None and recharge is None and recharge_amount is None:
        return None
    parts = []
    if charges is not None:
        parts.append(f"{strip_tags(str(charges))} charges")
    if recharge is not None:
        label = RECHARGE_LABELS.get(recharge, str(recharge))
        if recharge_amount is not None:
            parts.append(f"regains {strip_tags(str(recharge_amount))} at {label}")
        else:
            parts.append(f"all regain at {label}")
    elif recharge_amount is not None:
        parts.append(f"regains {strip_tags(str(recharge_amount))}")
    return ", ".join(parts) if parts else None


# ===========================================================================
# Structured-field atom extraction (priority 1)
# ===========================================================================

STRUCT_FIELDS = [
    "resist", "immune", "vulnerable", "conditionImmune", "modifySpeed",
    "bonusWeapon", "bonusAc", "bonusWeaponAttack", "bonusWeaponDamage",
    "bonusSavingThrow", "bonusSpellAttack", "bonusSpellSaveDc",
    "bonusAbilityCheck", "bonusSpellDamage", "charges", "recharge",
    "rechargeAmount", "poison", "poisonTypes", "curse", "sentient",
    "grantsProficiency", "grantsLanguage", "light", "stealth",
    "critThreshold", "ability", "attachedSpells", "focus", "wondrous",
    "customProperties",
]


def resolve_item_fields(raw):
    """Merge top-level fields with `inherits`/`_copy` fallbacks (magic
    variants / generic variants / compendium `_copy` reprints store their
    real data one level down)."""
    inh = raw.get("inherits") if isinstance(raw.get("inherits"), dict) else {}
    copy = raw.get("_copy") if isinstance(raw.get("_copy"), dict) else {}

    name = raw.get("name") or copy.get("name") or inh.get("name")
    source = raw.get("source") or inh.get("source") or copy.get("source")
    rarity = raw.get("rarity") if raw.get("rarity") is not None else inh.get("rarity")
    page = raw.get("page") if raw.get("page") is not None else inh.get("page")
    typ = raw.get("type") if raw.get("type") is not None else inh.get("type")

    entries_blobs = []
    for obj in (raw, inh):
        if obj.get("entries"):
            entries_blobs.append(obj["entries"])
        if obj.get("additionalEntries"):
            entries_blobs.append(obj["additionalEntries"])
    mod_texts = extract_mod_entries_text(copy)

    fields = {
        "name": name, "source": source, "rarity": rarity, "page": page,
        "type": typ, "entries_blobs": entries_blobs, "mod_texts": mod_texts,
    }
    for f in STRUCT_FIELDS:
        v = raw.get(f)
        if v is None:
            v = inh.get(f)
        fields[f] = v
    return fields


def _uses_from_attached_wrapper(outer_key, inner_key):
    if outer_key == "will":
        return "at will"
    if outer_key == "ritual":
        return "ritual (no charge)"
    if outer_key == "charges":
        return f"{inner_key} charges each" if inner_key else "charges"
    if outer_key == "daily":
        if inner_key and inner_key.endswith("e"):
            return f"{inner_key[:-1]}/day each"
        if inner_key:
            return f"{inner_key}/day total"
        return "per day"
    if outer_key == "rest":
        return f"{inner_key}/rest" if inner_key else "per rest"
    if outer_key == "limited":
        return "limited uses"
    return "special"


def structured_atoms(fields):
    atoms = []

    def add(category, subtype=None, trigger="passive", magnitude=None, uses=None):
        atoms.append(Atom(category, subtype, trigger, magnitude, uses))

    for fname, cat in (("resist", "resistance"), ("immune", "immunity"),
                       ("vulnerable", "vulnerability")):
        values = fields.get(fname)
        if not values:
            continue
        for el in values:
            if isinstance(el, str):
                add(cat, subtype=el.lower())
            elif isinstance(el, dict):
                types = el.get(fname) or []
                note = el.get("note")
                if not types and el.get("special"):
                    add(cat, subtype="special", magnitude=str(el["special"])[:100])
                    continue
                for t in types:
                    if isinstance(t, str):
                        add(cat, subtype=t.lower(), magnitude=note)

    cond_imm = fields.get("conditionImmune")
    if cond_imm:
        for el in cond_imm:
            if isinstance(el, str):
                add("condition immunity", subtype=CONDITION_ALIASES.get(el.lower(), el.lower()))
            elif isinstance(el, dict):
                if "special" in el:
                    add("condition immunity", subtype="special", magnitude=str(el["special"])[:100])
                else:
                    for t in el.get("conditionImmune", []):
                        if isinstance(t, str):
                            add("condition immunity", subtype=CONDITION_ALIASES.get(t.lower(), t.lower()))

    ms = fields.get("modifySpeed")
    if isinstance(ms, dict):
        for mode, data in ms.items():
            if not isinstance(data, dict):
                continue
            for spd_type, val in data.items():
                subtype = "all" if spd_type == "*" else str(spd_type).lower()
                if mode == "bonus":
                    add("movement speed", subtype, magnitude=f"+{val} ft")
                elif mode == "static":
                    add("movement speed", subtype, magnitude=f"{val} ft")
                elif mode == "equal":
                    add("movement speed", subtype, magnitude=f"= {val} speed")
                elif mode == "multiply":
                    add("movement speed", subtype, magnitude=f"x{val}")

    simple_bonus_map = [
        ("bonusWeapon", "weapon bonus", "attack and damage rolls", "passive"),
        ("bonusAc", "AC bonus", None, "passive"),
        ("bonusWeaponAttack", "attack bonus", "weapon attack rolls", "passive"),
        ("bonusWeaponDamage", "damage bonus", "weapon damage rolls", "on hit"),
        ("bonusSavingThrow", "saving throw bonus", "all", "passive"),
        ("bonusSpellAttack", "attack bonus", "spell attack rolls", "passive"),
        ("bonusSpellSaveDc", "spell save dc bonus", None, "passive"),
        ("bonusAbilityCheck", "ability check bonus", "all", "passive"),
        ("bonusSpellDamage", "spell damage bonus", None, "on hit"),
    ]
    for fname, cat, subtype, trig in simple_bonus_map:
        v = fields.get(fname)
        if v is not None:
            add(cat, subtype=subtype, trigger=trig, magnitude=str(v))

    ab = fields.get("ability")
    if isinstance(ab, dict):
        static = ab.get("static")
        if isinstance(static, dict):
            for k, val in static.items():
                if k in ABILS:
                    add("ability score bonus", subtype=ABILS[k], magnitude=f"set to {val}")
        if "choose" in ab:
            add("ability score bonus", subtype="choice", magnitude="choose (see item text)")
        fixed = ab.get("fixed")
        if isinstance(fixed, dict):
            for k, val in fixed.items():
                if k in ABILS:
                    add("ability score bonus", subtype=ABILS[k], magnitude=f"set to {val}")
        for k, val in ab.items():
            if k in ABILS and isinstance(val, (int, float)):
                add("ability score bonus", subtype=ABILS[k], magnitude=f"+{val}")

    if fields.get("poison"):
        ptypes = fields.get("poisonTypes") or []
        add("utility", subtype="poison", trigger="on exposure",
            magnitude="/".join(ptypes) if ptypes else None)

    if fields.get("curse"):
        add("curse", uses="permanent until removed")

    if fields.get("sentient"):
        add("sentience")

    if fields.get("grantsProficiency"):
        add("utility", subtype="proficiency granted")

    if fields.get("grantsLanguage"):
        add("utility", subtype="language granted")

    if fields.get("focus"):
        add("utility", subtype="spellcasting focus")

    if fields.get("stealth"):
        add("stealth", subtype="stealth disadvantage")

    ct = fields.get("critThreshold")
    if isinstance(ct, int) and 0 < ct < 20:
        add("attack bonus", subtype="expanded critical range", trigger="on attack roll",
            magnitude=f"crit on {ct}-20")

    lt = fields.get("light")
    if isinstance(lt, list) and lt and isinstance(lt[0], dict):
        b, d = lt[0].get("bright"), lt[0].get("dim")
        parts = []
        if b:
            parts.append(f"bright {b} ft")
        if d:
            parts.append(f"dim {d} ft")
        add("light/vision", subtype="emits light", magnitude=", ".join(parts) or None)

    asx = fields.get("attachedSpells")
    if isinstance(asx, list):
        for sp in asx:
            if isinstance(sp, str):
                name = sp.split("|")[0].strip().lower()
                if name:
                    add("spell granted", subtype=name, trigger="action")
    elif isinstance(asx, dict):
        for outer_key, inner in asx.items():
            if not isinstance(inner, dict):
                continue
            for inner_key, spells in inner.items():
                uses = _uses_from_attached_wrapper(outer_key, inner_key)
                if isinstance(spells, list):
                    for sp in spells:
                        if isinstance(sp, str):
                            name = sp.split("|")[0].strip().lower()
                            if name:
                                add("spell granted", subtype=name, trigger="action", uses=uses)

    return atoms


# ===========================================================================
# Prose / tag-derived heuristics (priority 2 + 3)
# ===========================================================================

RE_DAMAGE_EXTRA = re.compile(
    rf"\b(?:an?\s+)?(?:extra|additional|further|bonus)\s+({DICE_PAT})\s+{DMG_PAT}\s+damage", re.I)
RE_DAMAGE_INSTEAD = re.compile(rf"deals?\s+{DMG_PAT}\s+damage\s+instead\s+of", re.I)
RE_DAMAGE_TAKE = re.compile(
    rf"\btakes?\s+(?:an?\s+)?(?:extra\s+|additional\s+)?({DICE_PAT})\s+{DMG_PAT}\s+damage", re.I)

RE_RESIST = re.compile(r"\bresistan(?:ce|t) to ([a-z][a-z ,/\-']*?) damage", re.I)
RE_IMMUNE_DMG = re.compile(r"\bimmun(?:e|ity) to ([a-z][a-z ,/\-']*?) damage", re.I)
RE_VULN = re.compile(r"\bvulnerab(?:le|ility) to ([a-z][a-z ,/\-']*?) damage", re.I)

RE_COND_SAVE = re.compile(rf"saving throw or (?:be(?:come)?|fall|is)\s+{COND_PAT}", re.I)
RE_COND_BECOMES = re.compile(rf"\b(?:target|creature)\s+(?:becomes?|is)\s+{COND_PAT}\b", re.I)
RE_COND_IMMUNE = re.compile(
    rf"(?:immune to (?:the )?(?:being )?|can(?:'t|not) (?:be(?:come)?)\s+)"
    rf"({COND_NC}(?:[\s,]*(?:or|and)?[\s,]*{COND_NC})*)", re.I)

RE_SPEED = re.compile(
    r"\b(flying|swimming|climbing|burrowing|walking)\s+speed\s+(?:of\s+(\d+)\s*feet|equal to your walking speed)", re.I)
RE_SPEED_INCR = re.compile(
    r"\b(walking|flying|swimming|climbing|burrowing)?\s*speed increases by (\d+)\s*feet", re.I)

RE_TELEPORT = re.compile(r"\byou[^.]{0,50}?\bteleport", re.I)

RE_HEAL = re.compile(rf"\bregains?\s+({DICE_PAT})\s+hit points", re.I)
RE_TEMPHP = re.compile(rf"({DICE_PAT})\s+temporary hit points", re.I)

RE_AC_BONUS = re.compile(r"\+(\d+)\s+bonus to (?:your |its )?(?:armor class|ac)\b", re.I)
RE_AC_INCR = re.compile(r"(?:armor class|ac) increases by (\d+)", re.I)
RE_ATKDMG_BONUS = re.compile(r"\+(\d+)\s+bonus to attack and damage rolls", re.I)
RE_ATK_BONUS = re.compile(r"\+(\d+)\s+bonus to attack rolls\b", re.I)
RE_SAVE_BONUS = re.compile(r"\+(\d+)\s+bonus to saving throws(?:\s+against\s+([a-z][a-z ,]*?))?[.,]", re.I)

RE_ADV_SAVE_AGAINST = re.compile(
    r"(?<![a-zA-Z])advantage on [a-z, ]*?saving throws? against\s+([a-z][a-z ,]{0,40}?)"
    r"(?=[.,]|\s+(?:for|made|while|during|unless)\b|$)", re.I)
RE_ADV_SAVE_PLAIN = re.compile(
    r"(?<![a-zA-Z])advantage on [a-z, ]*?saving throws?\b(?!\s+against)", re.I)
RE_ADV_SKILL = re.compile(
    r"(?<![a-zA-Z])advantage on (?:[a-z]+\s+)?\(([A-Za-z ]+)\)\s+checks", re.I)
RE_ADV_ATTACK = re.compile(r"(?<![a-zA-Z])advantage on attack rolls\b", re.I)

RE_DISADV_SAVE_AGAINST = re.compile(
    r"disadvantage on [a-z, ]*?saving throws? against\s+([a-z][a-z ,]{0,40}?)"
    r"(?=[.,]|\s+(?:for|made|while|during|unless)\b|$)", re.I)
RE_DISADV_SAVE_PLAIN = re.compile(r"disadvantage on [a-z, ]*?saving throws?\b(?!\s+against)", re.I)
RE_DISADV_SKILL = re.compile(r"disadvantage on (?:[a-z]+\s+)?\(([A-Za-z ]+)\)\s+checks", re.I)
RE_DISADV_ATTACK = re.compile(r"disadvantage on attack rolls\b", re.I)

RE_REACTION = re.compile(r"use your reaction to ([^.]{3,90})", re.I)
REACTION_KEYWORDS = [
    ("reduce", "damage reduction"), ("negate", "negate effect"),
    ("redirect", "redirect damage"), ("resist", "resist damage"),
    ("miss", "turn attack into a miss"), ("half", "halve damage"),
    ("prevent", "prevent effect"), ("absorb", "absorb damage"),
    ("avoid", "avoid damage"), ("deflect", "deflect attack"),
    ("block", "block attack"), ("parry", "parry attack"),
    ("intercept", "intercept attack"), ("shield", "shield yourself"),
]

RE_LIGHT = re.compile(
    r"sheds?\s+bright light(?:\s+in a|\s+out to)?\s+(\d+)[- ]foot radius"
    r"(?:,?\s+and dim light for an additional\s+(\d+)\s*feet)?", re.I)
RE_DARKVISION = re.compile(r"darkvision\s+(?:out to a range of\s+|of\s+)?(\d+)\s*feet", re.I)
RE_SENSE_OTHER = re.compile(
    r"\b(truesight|blindsight|tremorsense)\s+(?:out to a range of\s+|of\s+)?(\d+)\s*feet", re.I)

RE_STEALTH_DIS = re.compile(r"disadvantage on (?:dexterity\s+)?\(?stealth\)?\s*(?:checks?|skill rolls?)?", re.I)

RE_CAST_PREFIX = re.compile(
    r"\bcast(?:s|ing)?\s+(?:either\s+)?(?:the\s+|a\s+|an\s+|that\s+|this\s+)?", re.I)
RE_SPELL_CAST_SUFFIX = re.compile(
    r"cast(?:s|ing)?\s+(?:the\s+)?([a-z][a-z'\- ]{1,40}?)\s+spell\b", re.I)

RE_ABIL_IS = re.compile(
    r"your (strength|dexterity|constitution|intelligence|wisdom|charisma)(?: score)? "
    r"(?:is|becomes) (\d+)", re.I)
RE_ABIL_INCR = re.compile(
    r"your (strength|dexterity|constitution|intelligence|wisdom|charisma)(?: score)? "
    r"increases by (\d+)", re.I)
RE_EXPERTISE = re.compile(
    r"expertise (?:in|with) (?:[a-z]+\s+)?\(([A-Za-z ]+)\)\s+checks?", re.I)
RE_ABIL_CHOICE_INCR = re.compile(
    r"increase one of your ability scores by (\d+)|increase your ability scores? by (\d+)", re.I)
RE_AC_BECOMES = re.compile(
    r"(?:armor class|ac) becomes (\d+)(?:\s*\+\s*your ([a-z]+) modifier)?", re.I)
RE_ADV_ABILITY_CHECK = re.compile(r"(?<![a-zA-Z])advantage on (?:any )?ability checks?\b", re.I)
RE_COUNTS_AS_MAGICAL = re.compile(r"count(?:s)? as magical", re.I)


def _split_damage_phrase(phrase, category, trailing=""):
    low = phrase.lower()
    qualifier = "nonmagical" if re.search(r"non-?magical", low + " " + trailing.lower()) else None
    tokens = re.split(r"[,/]", low.replace(" and ", ","))
    out = []
    for tok in tokens:
        tok = tok.strip().strip(".")
        tok = re.sub(r"^(non-?magical\s*)", "", tok).strip()
        if not tok:
            continue
        if tok == "all":
            out.append(Atom(category, "all", "passive", qualifier, None))
        elif tok in DAMAGE_TYPES_SET:
            out.append(Atom(category, tok, "passive", qualifier, None))
    return out


def prose_atoms(text):
    if not text:
        return []
    atoms = []
    covered_spans = []

    for m in RE_DAMAGE_EXTRA.finditer(text):
        dice, dtype = m.group(1), m.group(2).lower()
        before = window_before(text, m.start())
        trig = "on crit" if crit_nearby(text, m.start()) else "on hit"
        cat = "damage rider"
        ctx = before + text[m.start():min(len(text), m.end() + 60)]
        if has_any(ctx, ["saving throw", "radius", " cone", " line", "sphere", "each creature"]):
            cat = "area damage"
            trig = "bonus action" if has_any(before, ["bonus action"]) else (
                "reaction" if has_any(before, ["reaction"]) else "action")
        uses = local_uses(text, m.start(), m.end())
        atoms.append(Atom(cat, dtype, trig, dice, uses))
        covered_spans.append((m.start(), m.end()))

    for m in RE_DAMAGE_INSTEAD.finditer(text):
        atoms.append(Atom("damage rider", m.group(1).lower(), "on hit",
                           "(replaces weapon damage type)", "always"))

    for m in RE_DAMAGE_TAKE.finditer(text):
        if any(a <= m.start() <= b for a, b in covered_spans):
            continue
        if has_any(text[max(0, m.start() - 20):m.start()], ["extra", "additional", "further"]):
            continue
        before, after = window_before(text, m.start()), window_after(text, m.end())
        ctx = before + after
        if not has_any(ctx, ["saving throw", " hit ", "you hit", "hits "]):
            continue
        dice, dtype = m.group(1), m.group(2).lower()
        area = has_any(ctx, ["radius", "cone", "line", "sphere", "each creature", "emanation"])
        uses = local_uses(text, m.start(), m.end())
        if "saving throw" in ctx.lower() and area:
            cat = "area damage"
            trig = "bonus action" if has_any(before, ["bonus action"]) else (
                "reaction" if has_any(before, ["reaction"]) else "action")
        elif "saving throw" in ctx.lower():
            cat = "damage rider"
            trig = "on hit" if has_any(before, ["hit"]) else "on save fail"
        else:
            cat = "damage rider"
            trig = "on crit" if crit_nearby(text, m.start()) else "on hit"
        atoms.append(Atom(cat, dtype, trig, dice, uses))

    for m in RE_RESIST.finditer(text):
        atoms.extend(_split_damage_phrase(m.group(1), "resistance", text[m.end():m.end() + 40]))
    for m in RE_IMMUNE_DMG.finditer(text):
        atoms.extend(_split_damage_phrase(m.group(1), "immunity", text[m.end():m.end() + 40]))
    for m in RE_VULN.finditer(text):
        atoms.extend(_split_damage_phrase(m.group(1), "vulnerability", text[m.end():m.end() + 40]))

    for pat in (RE_COND_SAVE, RE_COND_BECOMES):
        for m in pat.finditer(text):
            cond = CONDITION_ALIASES.get(m.group(1).lower(), m.group(1).lower())
            before = window_before(text, m.start())
            trig = "on crit" if crit_nearby(text, m.start()) else (
                "on hit" if has_any(before, ["hit"]) else "on save fail")
            atoms.append(Atom("condition inflicted", cond, trig, None, None))

    for m in RE_COND_IMMUNE.finditer(text):
        phrase = m.group(1)
        for raw_cond in re.findall(COND_NC, phrase, re.I):
            cond = CONDITION_ALIASES.get(raw_cond.lower(), raw_cond.lower())
            atoms.append(Atom("condition immunity", cond, "passive", None, None))

    speed_name_map = {"flying": "fly", "swimming": "swim", "climbing": "climb",
                       "burrowing": "burrow", "walking": "walk"}
    for m in RE_SPEED.finditer(text):
        kind = speed_name_map[m.group(1).lower()]
        mag = f"{m.group(2)} ft" if m.group(2) else "= walking speed"
        dur_m = re.search(r"for (\d+) (hour|minute)s?", window_after(text, m.end(), 60), re.I)
        uses = f"{dur_m.group(1)} {dur_m.group(2)}(s)" if dur_m else None
        atoms.append(Atom("movement speed", kind, "passive", mag, uses))
    for m in RE_SPEED_INCR.finditer(text):
        kind = speed_name_map.get((m.group(1) or "walking").lower(), "walk")
        atoms.append(Atom("movement speed", kind, "passive", f"+{m.group(2)} ft", None))

    for m in RE_TELEPORT.finditer(text):
        before, after = window_before(text, m.start()), window_after(text, m.end())
        trig = "reaction" if has_any(before, ["reaction"]) else (
            "bonus action" if has_any(before, ["bonus action"]) else "action")
        rng_m = re.search(r"within (\d+) feet", before + after, re.I)
        atoms.append(Atom("teleport", None, trig, f"{rng_m.group(1)} ft" if rng_m else None,
                           local_uses(text, m.start(), m.end())))

    for m in RE_HEAL.finditer(text):
        if "temporary" in text[max(0, m.start() - 15):m.start()].lower():
            continue
        before = window_before(text, m.start())
        trig = "reaction" if has_any(before, ["reaction"]) else (
            "bonus action" if has_any(before, ["bonus action"]) else "action")
        atoms.append(Atom("healing", None, trig, m.group(1), local_uses(text, m.start(), m.end())))

    for m in RE_TEMPHP.finditer(text):
        before = window_before(text, m.start())
        trig = "reaction" if has_any(before, ["reaction"]) else (
            "bonus action" if has_any(before, ["bonus action"]) else "action")
        atoms.append(Atom("temp hp", None, trig, m.group(1), local_uses(text, m.start(), m.end())))

    for m in RE_AC_BONUS.finditer(text):
        trig = "reaction" if has_any(window_before(text, m.start()), ["reaction"]) else "passive"
        atoms.append(Atom("AC bonus", None, trig, f"+{m.group(1)}", None))
    for m in RE_AC_INCR.finditer(text):
        atoms.append(Atom("AC bonus", None, "passive", f"+{m.group(1)}", None))

    for m in RE_ATKDMG_BONUS.finditer(text):
        atoms.append(Atom("weapon bonus", "attack and damage rolls", "passive", f"+{m.group(1)}", None))
    for m in RE_ATK_BONUS.finditer(text):
        atoms.append(Atom("attack bonus", "attack rolls", "passive", f"+{m.group(1)}", None))

    for m in RE_SAVE_BONUS.finditer(text):
        subtype = m.group(2).strip().rstrip(".,") if m.group(2) else "all"
        atoms.append(Atom("saving throw bonus", subtype, "passive", f"+{m.group(1)}", None))

    for m in RE_ADV_SAVE_AGAINST.finditer(text):
        atoms.append(Atom("advantage", f"saving throws vs {m.group(1).strip()}", "passive", None, None))
    for m in RE_ADV_SAVE_PLAIN.finditer(text):
        atoms.append(Atom("advantage", "saving throws", "passive", None, None))
    for m in RE_ADV_SKILL.finditer(text):
        atoms.append(Atom("advantage", f"{m.group(1).strip()} checks", "passive", None, None))
    for m in RE_ADV_ATTACK.finditer(text):
        atoms.append(Atom("advantage", "attack rolls", "passive", None, None))

    for m in RE_DISADV_SAVE_AGAINST.finditer(text):
        atoms.append(Atom("disadvantage", f"saving throws vs {m.group(1).strip()}", "passive", None, None))
    for m in RE_DISADV_SAVE_PLAIN.finditer(text):
        atoms.append(Atom("disadvantage", "saving throws", "passive", None, None))
    for m in RE_DISADV_SKILL.finditer(text):
        atoms.append(Atom("disadvantage", f"{m.group(1).strip()} checks", "passive", None, None))
    for m in RE_DISADV_ATTACK.finditer(text):
        atoms.append(Atom("disadvantage", "attack rolls", "passive", None, None))

    for m in RE_REACTION.finditer(text):
        clause = m.group(1).lower()
        subtype = next((label for kw, label in REACTION_KEYWORDS if kw in clause), None)
        if subtype is None:
            continue
        dice_m = re.search(DICE_PAT, clause)
        atoms.append(Atom("reaction defence", subtype, "reaction",
                           dice_m.group(0) if dice_m else None, local_uses(text, m.start(), m.end())))

    for m in RE_LIGHT.finditer(text):
        b, d = m.group(1), m.group(2)
        mag = f"bright {b} ft" + (f", dim {d} ft" if d else "")
        atoms.append(Atom("light/vision", "emits light", "passive", mag, None))
    darkvision_found = False
    for m in RE_DARKVISION.finditer(text):
        darkvision_found = True
        atoms.append(Atom("light/vision", "darkvision", "passive", f"{m.group(1)} ft", None))
    if not darkvision_found and re.search(r"\bdarkvision\b", text, re.I):
        atoms.append(Atom("light/vision", "darkvision", "passive", None, None))
    other_sense_found = set()
    for m in RE_SENSE_OTHER.finditer(text):
        other_sense_found.add(m.group(1).lower())
        atoms.append(Atom("light/vision", m.group(1).lower(), "passive", f"{m.group(2)} ft", None))
    for sense in ("truesight", "blindsight", "tremorsense"):
        if sense not in other_sense_found and re.search(rf"\b{sense}\b", text, re.I):
            atoms.append(Atom("light/vision", sense, "passive", None, None))

    if RE_COUNTS_AS_MAGICAL.search(text):
        atoms.append(Atom("utility", "weapon counts as magical", "passive", None, None))

    for m in RE_STEALTH_DIS.finditer(text):
        atoms.append(Atom("stealth", "stealth disadvantage", "passive", None, None))

    if re.search(r"breathe (?:air and )?water|water breathing|breathe underwater", text, re.I):
        atoms.append(Atom("utility", "water breathing", "passive", None, None))
    if re.search(r"don'?t need to (?:eat|eat,? drink,? or breathe)|doesn'?t need to eat or drink", text, re.I):
        atoms.append(Atom("utility", "sustenance-free", "passive", None, None))
    if re.search(r"\byou (?:become|turn) invisible\b", text, re.I):
        atoms.append(Atom("utility", "self-invisibility", "action", None, None))
    if re.search(r"leaves? no tracks|can(?:not|'t) be tracked", text, re.I):
        atoms.append(Atom("utility", "untrackable", "passive", None, None))
    if re.search(r"can be used as a spellcasting focus", text, re.I):
        atoms.append(Atom("utility", "spellcasting focus", "passive", None, None))
    if re.search(r"can'?t be surprised", text, re.I):
        atoms.append(Atom("utility", "cannot be surprised", "passive", None, None))

    def _spell_grant_trig_uses(start, end):
        before = window_before(text, start)
        after = window_after(text, end, 70)
        trig = "bonus action" if has_any(before, ["bonus action"]) else (
            "reaction" if has_any(before, ["reaction"]) else "action")
        uses = None
        if has_any(after, ["at will"]):
            uses = "at will"
        else:
            freq = re.search(r"once per day|(\d+)\s*/\s*day|(\d+)\s+times? per day", after, re.I)
            if freq:
                uses = "once per day" if freq.group(0).lower().startswith("once") else \
                    f"{freq.group(1) or freq.group(2)}/day"
            elif has_any(after, ["short or long rest"]):
                uses = "1/short or long rest"
            elif has_any(after, ["long rest"]):
                uses = "1/long rest"
        return trig, uses

    for name, start, end in find_spell_grants(text, SPELL_NAMES_DESC):
        trig, uses = _spell_grant_trig_uses(start, end)
        atoms.append(Atom("spell granted", name, trig, None, uses))

    for m in RE_SPELL_CAST_SUFFIX.finditer(text):
        raw_name = m.group(1).strip()
        name = re.sub(r"^(a|an|the|that|this|you|it|special)\s+", "", raw_name, flags=re.I).strip()
        if not name or len(name) < 3:
            continue
        trig, uses = _spell_grant_trig_uses(m.start(), m.end())
        atoms.append(Atom("spell granted", name.lower(), trig, None, uses))

    for m in RE_ABIL_IS.finditer(text):
        atoms.append(Atom("ability score bonus", m.group(1).capitalize(), "passive",
                           f"set to {m.group(2)}", None))
    for m in RE_ABIL_INCR.finditer(text):
        atoms.append(Atom("ability score bonus", m.group(1).capitalize(), "passive",
                           f"+{m.group(2)}", None))
    for m in RE_EXPERTISE.finditer(text):
        atoms.append(Atom("ability check bonus", f"{m.group(1).strip()} (expertise)", "passive",
                           "expertise", None))
    for m in RE_ABIL_CHOICE_INCR.finditer(text):
        amt = m.group(1) or m.group(2)
        atoms.append(Atom("ability score bonus", "choice", "passive", f"+{amt}", None))
    for m in RE_AC_BECOMES.finditer(text):
        mag = f"set to {m.group(1)}" + (f" + {m.group(2)} modifier" if m.group(2) else "")
        atoms.append(Atom("AC bonus", None, "passive", mag, None))
    for m in RE_ADV_ABILITY_CHECK.finditer(text):
        atoms.append(Atom("advantage", "ability checks", "passive", None, None))

    return atoms


def finalize_uses(atom, item_uses):
    if atom.uses:
        return atom
    if atom.category in PASSIVE_CATEGORIES:
        return atom._replace(uses="always")
    if atom.category in AT_WILL_DEFAULT_CATEGORIES:
        return atom._replace(uses="at will")
    if atom.category == "condition inflicted" and atom.trigger in ("on hit", "on crit") and not item_uses:
        return atom._replace(uses="at will")
    return atom._replace(uses=item_uses or "unknown")


def dedup_atoms(atoms):
    """Collapse exact-duplicate (category, subtype, trigger, magnitude)
    atoms within one item (same pattern can be found by both the
    structured-field pass and the prose pass); keep the first uses value
    found among duplicates."""
    seen = {}
    order = []
    for a in atoms:
        key = (a.category, a.subtype, a.trigger, a.magnitude)
        if key not in seen:
            seen[key] = a
            order.append(key)
        elif not seen[key].uses and a.uses:
            seen[key] = seen[key]._replace(uses=a.uses)
    return [seen[k] for k in order]


# ===========================================================================
# Summary synthesis (never copies source prose)
# ===========================================================================

def make_summary(atom):
    cat, sub, trig, mag, uses = atom
    if cat == "damage rider":
        s = f"extra {mag or '?'} {sub or ''} damage".replace("  ", " ").strip()
        if trig == "on crit":
            s += " on a critical hit"
    elif cat == "area damage":
        s = f"{mag or '?'} {sub or ''} damage to an area".replace("  ", " ").strip()
    elif cat == "resistance":
        s = f"resistance to {sub or 'damage'}" + (f" ({mag})" if mag else "")
    elif cat == "immunity":
        s = f"immunity to {sub or 'damage'}" + (f" ({mag})" if mag else "")
    elif cat == "vulnerability":
        s = f"vulnerability to {sub or 'damage'}" + (f" ({mag})" if mag else "")
    elif cat == "condition inflicted":
        s = f"inflicts {sub}"
    elif cat == "condition immunity":
        s = f"immune to {sub}"
    elif cat == "movement speed":
        s = f"{sub} speed {mag or ''}".strip()
    elif cat == "teleport":
        s = "teleport" + (f" ({mag})" if mag else "")
    elif cat == "healing":
        s = f"restores {mag or '?'} hit points"
    elif cat == "temp hp":
        s = f"grants {mag or '?'} temporary hit points"
    elif cat == "AC bonus":
        s = f"{mag or '?'} bonus to AC"
    elif cat == "weapon bonus":
        s = f"{mag or '?'} bonus to {sub or 'weapon attack and damage rolls'}"
    elif cat == "attack bonus":
        s = f"{mag or '?'} bonus to {sub or 'attack rolls'}"
    elif cat == "damage bonus":
        s = f"{mag or '?'} bonus {sub or 'damage'}"
    elif cat == "saving throw bonus":
        s = f"{mag or '?'} bonus to {sub or 'all'} saving throws"
    elif cat == "spell save dc bonus":
        s = f"{mag or '?'} to spell save DC"
    elif cat == "spell damage bonus":
        s = f"{mag or '?'} bonus to spell damage"
    elif cat == "ability check bonus":
        s = f"{mag or '?'} bonus to {sub or 'all'} checks"
    elif cat == "ability score bonus":
        s = f"{sub or 'ability score'} {mag or ''}".strip()
    elif cat == "advantage":
        s = f"advantage on {sub}"
    elif cat == "disadvantage":
        s = f"disadvantage on {sub}"
    elif cat == "spell granted":
        s = f"grants the {sub} spell"
    elif cat == "reaction defence":
        s = f"reaction: {sub}" + (f" ({mag})" if mag else "")
    elif cat == "light/vision":
        s = f"{sub}" + (f" {mag}" if mag else "")
    elif cat == "stealth":
        s = sub or "stealth effect"
    elif cat == "sentience":
        s = "sentient item"
    elif cat == "curse":
        s = "cursed item"
    else:  # utility and any future category
        s = sub or cat
    if uses and uses not in ("always",):
        s += f"; {uses}"
    return s[:300]


# ===========================================================================
# Magnitude summarisation
# ===========================================================================

_DICE_FULL_RE = re.compile(r"^([+-]?)(\d+)d(\d+)\s*([+-]\s*\d+)?$")
_NUM_RE = re.compile(r"^([+-]?\d+(?:\.\d+)?)$")


def _magnitude_power(s):
    if not s:
        return None
    s = s.strip()
    m = _DICE_FULL_RE.match(s)
    if m:
        sign = -1 if m.group(1) == "-" else 1
        n, d = int(m.group(2)), int(m.group(3))
        k = m.group(4)
        k = int(k.replace(" ", "")) if k else 0
        return sign * (n * (d + 1) / 2) + k
    m2 = _NUM_RE.match(s)
    if m2:
        return float(m2.group(1))
    return None


def summarize_magnitudes(values):
    scored = [(p, v) for v in values if v for p in [_magnitude_power(v)] if p is not None]
    if not scored:
        return None
    scored.sort(key=lambda x: x[0])
    lo, hi = scored[0][1], scored[-1][1]
    return lo if lo == hi else f"{lo} - {hi}"


# ===========================================================================
# Homebrew corpus loading
# ===========================================================================

def load_corpus():
    """Single pass over every brew file: collect _meta.sources, custom
    itemType name definitions, and every raw item/baseitem/magicvariant/
    itemGroup record with its origin file (for dedup + brew_file)."""
    sources = {}
    custom_type_names = {}
    raw_items = []  # list of (raw_dict, brew_file_relpath)

    for d in SCAN_DIRS:
        paths = sorted(glob.glob(os.path.join(HOMEBREW_ROOT, d, "*.json")))
        for path in paths:
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except Exception as exc:  # malformed brew file; skip, keep going
                print(f"warning: failed to parse {path}: {exc}", file=sys.stderr)
                continue
            rel = os.path.relpath(path, HOMEBREW_ROOT)

            meta = data.get("_meta") or {}
            for s in meta.get("sources") or []:
                if not isinstance(s, dict):
                    continue
                rec = {
                    "full": s.get("full"),
                    "authors": s.get("authors") or [],
                    "url": s.get("url"),
                }
                for key_field in ("json", "abbreviation"):
                    abbr = s.get(key_field)
                    if abbr and abbr not in sources:
                        sources[abbr] = rec

            for te in data.get("itemType") or []:
                if isinstance(te, dict) and te.get("abbreviation") and te.get("name"):
                    custom_type_names.setdefault((te["abbreviation"], te.get("source")), te["name"])

            for key in ITEM_ARRAY_KEYS:
                for it in data.get(key) or []:
                    if isinstance(it, dict):
                        raw_items.append((it, rel))

    return sources, custom_type_names, raw_items


def dedup_items(raw_items):
    """Deduplicate by (name, source) across item/ + collection/ + baseitem/
    + magicvariant/, keeping the first match (SCAN_DIRS priority order)."""
    seen = {}
    order = []
    for raw, brew_file in raw_items:
        fields = resolve_item_fields(raw)
        name = fields.get("name") or "Unknown Item"
        source = fields.get("source") or "UNKNOWN"
        key = (name.strip().lower(), source.strip().lower())
        if key in seen:
            continue
        seen[key] = (raw, fields, brew_file)
        order.append(key)
    return [seen[k] for k in order]


SPELL_NAMES_DESC = []  # populated by compute_spell_names() in build(); longest names first
_SPELL_TAG_RE = re.compile(r"\{@spell\s+([^{}|]+)(?:\|[^{}]*)?\}", re.I)


def _clean_harvested_spell_name(name):
    name = re.sub(r"#\w+$", "", name).strip()
    name = re.sub(r"\s*\(u\.?a\.?\)$", "", name, flags=re.I).strip()
    return name


def compute_spell_names(unique_items):
    """Harvest every spell name mentioned via a {@spell ...} tag or the
    `attachedSpells` structured field anywhere in the (already deduped)
    corpus. Used to recognise "cast <spell>" prose that omits the word
    "spell" and/or the attachedSpells field (see RE_CAST_PREFIX)."""
    names = set()

    def harvest(v):
        if isinstance(v, str):
            nm = _clean_harvested_spell_name(v.split("|")[0].strip().lower())
            if nm:
                names.add(nm)
        elif isinstance(v, list):
            for x in v:
                harvest(x)
        elif isinstance(v, dict):
            for x in v.values():
                harvest(x)

    for _raw, fields, _brew_file in unique_items:
        raw_text = " ".join(flatten_text(fields["entries_blobs"]))
        for m in _SPELL_TAG_RE.finditer(raw_text):
            nm = _clean_harvested_spell_name(m.group(1).strip().lower())
            if nm:
                names.add(nm)
        harvest(fields.get("attachedSpells"))

    names = {n for n in names if len(n) >= 3}
    return sorted(names, key=len, reverse=True)


def find_spell_grants(text, spell_names_desc):
    """Find every "cast ... <known spell name>" occurrence in `text`,
    matching against a curated name list rather than requiring the
    literal word "spell" to follow (homebrew text very often omits it,
    e.g. "cast fireball once per long rest"). Returns (name, start, end)
    tuples; `end` is the position right after the matched spell name."""
    out = []
    if not spell_names_desc:
        return out
    for m in RE_CAST_PREFIX.finditer(text):
        pos = m.end()
        start = m.start()
        while True:
            chunk = text[pos:pos + 60].lower()
            name = None
            for cand in spell_names_desc:
                if chunk.startswith(cand):
                    nxt = chunk[len(cand):len(cand) + 1]
                    if nxt == "" or not nxt.isalnum():
                        name = cand
                        break
            if not name:
                break
            out.append((name, start, pos + len(name)))
            pos += len(name)
            cont = re.match(r"\s*(?:,\s*)?or\s+(?:the\s+)?", text[pos:pos + 15], re.I)
            if not cont:
                break
            pos += cont.end()
            start = pos
    return out


# ===========================================================================
# Handout markdown parsing
# ===========================================================================

HANDOUT_FILES = [
    {"path": "ores-and-ingots.md", "label": "ores-and-ingots",
     "forms": [("weapon", 5), ("armour", 6)]},
    {"path": "Hides-and-leather.md", "label": "hides-and-leather",
     "forms": [("light armour", 5), ("medium armour", 6)]},
    {"path": "woods-and-branches.md", "label": "woods-and-branches",
     "forms": [("weapon", 5), ("casting focus", 6)]},
]


def _br_to_newlines(cell):
    cell = cell.replace("<br><br>", "\n\n").replace("<br>", "\n")
    return cell.strip()


def parse_markdown_table_rows(text):
    rows = []
    seen_header = False
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if not seen_header:
            seen_header = True
            continue
        if all(set(c) <= set("-: ") for c in cells):
            continue  # the |---|---| separator row
        rows.append(cells)
    return rows


def parse_handouts():
    """Returns a list of material dicts:
    {handout, name, rarity, difficulty_modifier, gold_cost, gold_cost_gp,
     description, forms: [{form, effect_name, effect_text, atoms}]}"""
    materials = []
    for cfg in HANDOUT_FILES:
        path = os.path.join(REPO_ROOT, cfg["path"])
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        rows = parse_markdown_table_rows(text)
        for cells in rows:
            if len(cells) < 5:
                continue
            name = re.sub(r"^\*\*(.+)\*\*$", r"\1", cells[0].strip())
            description = _br_to_newlines(cells[1]) if len(cells) > 1 else None
            difficulty_modifier = cells[2].strip() if len(cells) > 2 else None
            rarity = normalize_rarity(cells[3]) if len(cells) > 3 else "unknown"
            gold_cost_raw = cells[4].strip() if len(cells) > 4 else None
            gold_m = re.search(r"([\d,]+)", gold_cost_raw or "")
            gold_cost_gp = int(gold_m.group(1).replace(",", "")) if gold_m else None

            forms = []
            for form_name, idx in cfg["forms"]:
                if idx >= len(cells):
                    continue
                cell_text = _br_to_newlines(cells[idx])
                if not cell_text:
                    continue
                name_m = re.match(r"^\*\*(.+?)\*\*", cell_text)
                effect_name = name_m.group(1).strip() if name_m else None
                atoms = prose_atoms(collapse_parenthetical_dice(cell_text))
                atoms = [finalize_uses(a, None) for a in atoms]
                atoms = dedup_atoms(atoms)
                forms.append({
                    "form": form_name,
                    "effect_name": effect_name,
                    "effect_text": cell_text,
                    "atoms": atoms,
                })

            materials.append({
                "handout": cfg["label"],
                "name": name,
                "rarity": rarity,
                "difficulty_modifier": difficulty_modifier,
                "gold_cost": gold_cost_raw,
                "gold_cost_gp": gold_cost_gp,
                "description": description,
                "forms": forms,
            })
    return materials


# ===========================================================================
# Main build pipeline
# ===========================================================================

def build():
    os.makedirs(DATA_DIR, exist_ok=True)

    print("Loading homebrew corpus (collection/, item/, baseitem/, magicvariant/)...")
    sources, custom_type_names, raw_items = load_corpus()
    print(f"  {len(raw_items)} raw item/baseitem/magicvariant/itemGroup records across "
          f"{sum(len(glob.glob(os.path.join(HOMEBREW_ROOT, d, '*.json'))) for d in SCAN_DIRS)} files")

    unique_items = dedup_items(raw_items)
    print(f"  {len(unique_items)} unique items after (name, source) dedup")

    SPELL_NAMES_DESC.extend(compute_spell_names(unique_items))
    print(f"  {len(SPELL_NAMES_DESC)} distinct spell names harvested for prose spell-grant matching")

    # pattern_key -> aggregation state
    pattern_registry = {}

    def get_bucket(key):
        if key not in pattern_registry:
            pattern_registry[key] = {
                "items": set(), "occurrences": [], "rarity_counter": Counter(),
                "type_counter": Counter(), "magnitudes": [],
            }
        return pattern_registry[key]

    item_summary_rows = []
    zero_atom_count = 0

    for raw, fields, brew_file in unique_items:
        name = fields["name"] or "Unknown Item"
        source_abbrev = fields["source"] or "UNKNOWN"
        rarity = normalize_rarity(fields.get("rarity"))
        page = normalize_page(fields.get("page"))
        item_type = resolve_item_type(fields.get("type"), source_abbrev, custom_type_names)
        if not item_type and fields.get("wondrous"):
            item_type = "Wondrous Item"
        book = (sources.get(source_abbrev) or {}).get("full") or source_abbrev

        raw_text = " ".join(flatten_text(fields["entries_blobs"])) + " " + " ".join(fields["mod_texts"])
        plain_text = collapse_parenthetical_dice(strip_tags(raw_text))
        cust_type = fields.get("customProperties")
        cust_type = cust_type.get("type") if isinstance(cust_type, dict) else None
        if cust_type in DAMAGE_TYPES_SET and "elemental damage" in plain_text.lower():
            plain_text = re.sub(r"\belemental damage\b", f"{cust_type} damage", plain_text, flags=re.I)

        atoms = structured_atoms(fields) + prose_atoms(plain_text)
        item_uses = format_uses(fields.get("charges"), fields.get("recharge"), fields.get("rechargeAmount"))
        atoms = [finalize_uses(a, item_uses) for a in atoms]
        atoms = dedup_atoms(atoms)

        if not atoms:
            zero_atom_count += 1

        item_key = (name.strip().lower(), source_abbrev.strip().lower())
        for atom in atoms:
            pkey = (atom.category, atom.subtype, atom.trigger)
            bucket = get_bucket(pkey)
            bucket["items"].add(item_key)
            bucket["rarity_counter"][rarity] += 1
            bucket["type_counter"][item_type or "unknown"] += 1
            if atom.magnitude:
                bucket["magnitudes"].append(atom.magnitude)
            bucket["occurrences"].append({
                "item_name": name, "source_abbrev": source_abbrev, "book": book,
                "page": page, "brew_file": brew_file, "rarity": rarity,
                "item_type": item_type, "magnitude": atom.magnitude,
                "uses": atom.uses, "summary": make_summary(atom),
            })

        item_summary_rows.append({
            "item_name": name, "source_abbrev": source_abbrev, "book": book,
            "page": page, "brew_file": brew_file, "rarity": rarity,
            "item_type": item_type, "atom_count": len(atoms),
        })

    print(f"  {zero_atom_count} items ({zero_atom_count / max(1, len(unique_items)):.1%}) "
          f"yielded no effect atom")
    print(f"  {len(pattern_registry)} distinct (category, subtype, trigger) patterns from homebrew")

    print("Parsing handout materials (Hides-and-leather.md, ores-and-ingots.md, woods-and-branches.md)...")
    handout_materials = parse_handouts()
    n_handout_atoms = 0
    for mat in handout_materials:
        for form in mat["forms"]:
            for atom in form["atoms"]:
                pkey = (atom.category, atom.subtype, atom.trigger)
                get_bucket(pkey)  # ensure the pattern exists even if homebrew never used it
                n_handout_atoms += 1
    print(f"  {len(handout_materials)} materials, {n_handout_atoms} handout effect atoms, "
          f"{len(pattern_registry)} total distinct patterns after merge")

    # Assign effect_id deterministically
    effect_ids = {}
    for i, pkey in enumerate(sorted(pattern_registry.keys(), key=lambda k: (k[0], k[1] or "", k[2] or "")), start=1):
        effect_ids[pkey] = i

    # ---------------------------------------------------------------------
    # Write SQLite database
    # ---------------------------------------------------------------------
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.executescript(
        """
        CREATE TABLE source_book (
            abbrev  TEXT PRIMARY KEY,
            full    TEXT,
            authors TEXT,   -- JSON array of author names
            url     TEXT
        );

        CREATE TABLE effect (
            effect_id         INTEGER PRIMARY KEY,
            category          TEXT NOT NULL,
            subtype           TEXT,
            trigger           TEXT,
            item_count        INTEGER NOT NULL,   -- distinct homebrew items with this pattern
            occurrence_count  INTEGER NOT NULL,   -- rows in effect_occurrence for this pattern
            magnitude_values  TEXT,               -- JSON sorted list of distinct magnitudes seen
            magnitude_summary TEXT,               -- e.g. "1d6 - 3d10" or a single value
            rarity_counts     TEXT,               -- JSON {rarity: occurrence_count}
            item_type_counts  TEXT                -- JSON {item_type: occurrence_count}
        );

        CREATE TABLE effect_occurrence (
            occurrence_id INTEGER PRIMARY KEY,
            effect_id     INTEGER NOT NULL REFERENCES effect(effect_id),
            item_name     TEXT NOT NULL,
            source_abbrev TEXT NOT NULL,
            book          TEXT,
            page          INTEGER,
            brew_file     TEXT NOT NULL,
            rarity        TEXT,
            item_type     TEXT,
            magnitude     TEXT,
            uses          TEXT,
            summary       TEXT NOT NULL
        );

        CREATE TABLE item_summary (
            item_summary_id INTEGER PRIMARY KEY,
            item_name       TEXT NOT NULL,
            source_abbrev   TEXT NOT NULL,
            book            TEXT,
            page            INTEGER,
            brew_file       TEXT NOT NULL,
            rarity          TEXT,
            item_type       TEXT,
            atom_count      INTEGER NOT NULL
        );

        CREATE TABLE handout_material (
            material_id         INTEGER PRIMARY KEY,
            handout              TEXT NOT NULL,
            name                 TEXT NOT NULL,
            rarity               TEXT,
            difficulty_modifier  TEXT,
            gold_cost            TEXT,
            gold_cost_gp         INTEGER,
            description          TEXT,
            UNIQUE(handout, name)
        );

        CREATE TABLE handout_material_form (
            form_id     INTEGER PRIMARY KEY,
            material_id INTEGER NOT NULL REFERENCES handout_material(material_id),
            form        TEXT NOT NULL,
            effect_name TEXT,
            effect_text TEXT NOT NULL,
            UNIQUE(material_id, form)
        );

        CREATE TABLE handout_material_atom (
            atom_id   INTEGER PRIMARY KEY,
            form_id   INTEGER NOT NULL REFERENCES handout_material_form(form_id),
            effect_id INTEGER NOT NULL REFERENCES effect(effect_id),
            category  TEXT NOT NULL,
            subtype   TEXT,
            trigger   TEXT,
            magnitude TEXT,
            uses      TEXT
        );

        CREATE INDEX idx_effect_cat_sub ON effect(category, subtype);
        CREATE INDEX idx_occurrence_effect ON effect_occurrence(effect_id);
        CREATE INDEX idx_occurrence_source ON effect_occurrence(source_abbrev);
        CREATE INDEX idx_item_summary_source ON item_summary(source_abbrev);
        CREATE INDEX idx_handout_form_material ON handout_material_form(material_id);
        CREATE INDEX idx_handout_atom_form ON handout_material_atom(form_id);
        CREATE INDEX idx_handout_atom_effect ON handout_material_atom(effect_id);
        """
    )

    # source_book: every abbreviation actually referenced by an item/occurrence
    used_sources = {row["source_abbrev"] for row in item_summary_rows}
    for abbr in sorted(used_sources):
        rec = sources.get(abbr) or {}
        cur.execute(
            "INSERT INTO source_book (abbrev, full, authors, url) VALUES (?, ?, ?, ?)",
            (abbr, rec.get("full") or abbr, json.dumps(rec.get("authors") or []), rec.get("url")),
        )

    # effect + effect_occurrence
    for pkey, bucket in pattern_registry.items():
        eid = effect_ids[pkey]
        category, subtype, trig = pkey
        occ = bucket["occurrences"]
        mag_values = sorted(set(bucket["magnitudes"]))
        cur.execute(
            """INSERT INTO effect (effect_id, category, subtype, trigger, item_count,
                                    occurrence_count, magnitude_values, magnitude_summary,
                                    rarity_counts, item_type_counts)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (eid, category, subtype, trig, len(bucket["items"]), len(occ),
             json.dumps(mag_values), summarize_magnitudes(mag_values),
             json.dumps(dict(bucket["rarity_counter"])), json.dumps(dict(bucket["type_counter"]))),
        )
        cur.executemany(
            """INSERT INTO effect_occurrence (effect_id, item_name, source_abbrev, book, page,
                                               brew_file, rarity, item_type, magnitude, uses, summary)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(eid, o["item_name"], o["source_abbrev"], o["book"], o["page"], o["brew_file"],
              o["rarity"], o["item_type"], o["magnitude"], o["uses"], o["summary"]) for o in occ],
        )

    # item_summary
    cur.executemany(
        """INSERT INTO item_summary (item_name, source_abbrev, book, page, brew_file,
                                      rarity, item_type, atom_count)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        [(r["item_name"], r["source_abbrev"], r["book"], r["page"], r["brew_file"],
          r["rarity"], r["item_type"], r["atom_count"]) for r in item_summary_rows],
    )

    # handout_material / handout_material_form / handout_material_atom
    for mat in handout_materials:
        cur.execute(
            """INSERT INTO handout_material (handout, name, rarity, difficulty_modifier,
                                              gold_cost, gold_cost_gp, description)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (mat["handout"], mat["name"], mat["rarity"], mat["difficulty_modifier"],
             mat["gold_cost"], mat["gold_cost_gp"], mat["description"]),
        )
        material_id = cur.lastrowid
        for form in mat["forms"]:
            cur.execute(
                """INSERT INTO handout_material_form (material_id, form, effect_name, effect_text)
                   VALUES (?, ?, ?, ?)""",
                (material_id, form["form"], form["effect_name"], form["effect_text"]),
            )
            form_id = cur.lastrowid
            for atom in form["atoms"]:
                pkey = (atom.category, atom.subtype, atom.trigger)
                cur.execute(
                    """INSERT INTO handout_material_atom (form_id, effect_id, category, subtype,
                                                            trigger, magnitude, uses)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (form_id, effect_ids[pkey], atom.category, atom.subtype, atom.trigger,
                     atom.magnitude, atom.uses),
                )

    conn.commit()

    # ---------------------------------------------------------------------
    # Report
    # ---------------------------------------------------------------------
    print()
    print(f"Wrote {DB_PATH}")
    for tbl in ("source_book", "effect", "effect_occurrence", "item_summary",
                "handout_material", "handout_material_form", "handout_material_atom"):
        n = cur.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        print(f"  {tbl}: {n} rows")

    n_items_total = len(item_summary_rows)
    n_zero = zero_atom_count
    print()
    print(f"Items with zero extracted effect atoms: {n_zero} / {n_items_total} "
          f"({n_zero / max(1, n_items_total):.1%})")

    n_mat = cur.execute("SELECT COUNT(*) FROM handout_material").fetchone()[0]
    print(f"Handout materials captured: {n_mat} "
          f"(ores-and-ingots + hides-and-leather + woods-and-branches)")

    print()
    print("Sample effect rows (damage rider / fire):")
    for row in cur.execute(
        "SELECT effect_id, category, subtype, trigger, item_count, occurrence_count, "
        "magnitude_summary, rarity_counts FROM effect WHERE category='damage rider' AND subtype='fire'"
    ):
        print(" ", row)

    conn.close()


if __name__ == "__main__":
    build()
