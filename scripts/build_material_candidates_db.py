#!/usr/bin/env python3
"""Build data/material_candidates.db from the TheGiddyLimit/homebrew item corpus.

Scans every item-like entry (item / baseitem / magicvariant / itemGroup) across
ref/homebrew/{collection,item,baseitem,magicvariant}/*.json for phrases that imply
a named crafting material (e.g. "Owlbear Leather Armour" -> material "Owlbear
Leather", base item "Leather Armour"), normalises the material names, and writes
three tables: material, material_reference, source_book.

This is a heuristic regex/dictionary pipeline, not NLP -- see the "known
gaps/heuristics" section in the project report for what it does and doesn't
catch well.

Usage:
    python3 scripts/build_material_candidates_db.py

Requires only the Python 3 standard library (json, re, sqlite3, pathlib).
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOMEBREW_ROOT = REPO_ROOT / "ref" / "homebrew"
DB_PATH = REPO_ROOT / "data" / "material_candidates.db"
SCAN_DIRS = ["collection", "item", "baseitem", "magicvariant"]
HANDOUT_FILES = [
    REPO_ROOT / "Hides-and-leather.md",
    REPO_ROOT / "ores-and-ingots.md",
    REPO_ROOT / "woods-and-branches.md",
]

RARITY_ORDER = ["none", "common", "uncommon", "rare", "very rare", "legendary",
                 "artifact", "varies", "unknown"]
CONFIDENCE_ORDER = ["high", "medium", "low"]
CONFIDENCE_RANK = {c: i for i, c in enumerate(CONFIDENCE_ORDER)}

# =====================================================================
# 1. Material-noun vocabulary
# =====================================================================
# Surface form (singular/plural) -> (canonical display noun, material_class).
# material_class is one of: leather/hide, metal, wood, bone, scale, cloth/silk,
# crystal/stone, other.
SUFFIX_NOUNS = {
    "leather": ("Leather", "leather/hide"), "leathers": ("Leather", "leather/hide"),
    "hide": ("Hide", "leather/hide"), "hides": ("Hide", "leather/hide"),
    "pelt": ("Pelt", "leather/hide"), "pelts": ("Pelt", "leather/hide"),
    "fur": ("Fur", "leather/hide"), "furs": ("Fur", "leather/hide"),
    "rawhide": ("Rawhide", "leather/hide"), "rawhides": ("Rawhide", "leather/hide"),
    "scale": ("Scale", "scale"), "scales": ("Scale", "scale"),
    "bone": ("Bone", "bone"), "bones": ("Bone", "bone"),
    "chitin": ("Chitin", "bone"), "chitins": ("Chitin", "bone"),
    "carapace": ("Carapace", "bone"), "carapaces": ("Carapace", "bone"),
    "silk": ("Silk", "cloth/silk"), "silks": ("Silk", "cloth/silk"),
    "web": ("Webbing", "cloth/silk"), "webs": ("Webbing", "cloth/silk"),
    "webbing": ("Webbing", "cloth/silk"),
    "feather": ("Feather", "other"), "feathers": ("Feather", "other"),
    "wood": ("Wood", "wood"), "woods": ("Wood", "wood"),
    "bark": ("Bark", "wood"), "barks": ("Bark", "wood"),
    "root": ("Root", "wood"), "roots": ("Root", "wood"),
    "branch": ("Branch", "wood"), "branches": ("Branch", "wood"),
    "timber": ("Timber", "wood"), "timbers": ("Timber", "wood"),
    "heartwood": ("Heartwood", "wood"),
    "steel": ("Steel", "metal"), "steels": ("Steel", "metal"),
    "iron": ("Iron", "metal"), "irons": ("Iron", "metal"),
    "ore": ("Ore", "metal"), "ores": ("Ore", "metal"),
    "ingot": ("Ingot", "metal"), "ingots": ("Ingot", "metal"),
    "alloy": ("Alloy", "metal"), "alloys": ("Alloy", "metal"),
    "metal": ("Metal", "metal"), "metals": ("Metal", "metal"),
    "glass": ("Glass", "crystal/stone"), "glasses": ("Glass", "crystal/stone"),
    "crystal": ("Crystal", "crystal/stone"), "crystals": ("Crystal", "crystal/stone"),
    "stone": ("Stone", "crystal/stone"), "stones": ("Stone", "crystal/stone"),
    "gem": ("Gem", "crystal/stone"), "gems": ("Gem", "crystal/stone"),
    "gemstone": ("Gemstone", "crystal/stone"), "gemstones": ("Gemstone", "crystal/stone"),
}
_noun_forms_sorted = sorted(SUFFIX_NOUNS.keys(), key=len, reverse=True)
NOUN_ALT = "|".join(re.escape(w) for w in _noun_forms_sorted)

# Named special materials that normally appear WITHOUT a suffix noun
# (e.g. "mithral", "darkwood"), per the assignment's explicit examples plus a
# curated list of other well-known D&D special materials.
NAMED_MATERIALS = {
    "mithral": {"display": "Mithral", "class": "metal",
                "forms": ["mithral", "mithril", "mithrals", "mithrils"]},
    "adamantine": {"display": "Adamantine", "class": "metal",
                   "forms": ["adamantine", "adamantite", "adamantites", "adamant"]},
    "darkwood": {"display": "Darkwood", "class": "wood", "forms": ["darkwood"]},
    "ironwood": {"display": "Ironwood", "class": "wood", "forms": ["ironwood"]},
    "dragonhide": {"display": "Dragonhide", "class": "leather/hide", "forms": ["dragonhide"]},
    "dragonscale": {"display": "Dragonscale", "class": "scale", "forms": ["dragonscale"]},
    "dragonbone": {"display": "Dragonbone", "class": "bone", "forms": ["dragonbone"]},
    "obsidian": {"display": "Obsidian", "class": "crystal/stone", "forms": ["obsidian"]},
    "orichalcum": {"display": "Orichalcum", "class": "metal", "forms": ["orichalcum"]},
    "byeshk": {"display": "Byeshk", "class": "metal", "forms": ["byeshk"]},
    "starmetal": {"display": "Star Metal", "class": "metal", "forms": ["starmetal"]},
    "meteoriciron": {"display": "Meteoric Iron", "class": "metal",
                      "forms": ["meteoric iron", "meteoritic iron"]},
    "moonsilver": {"display": "Moonsilver", "class": "metal", "forms": ["moonsilver"]},
    "truesilver": {"display": "Truesilver", "class": "metal", "forms": ["truesilver"]},
    "voidsteel": {"display": "Voidsteel", "class": "metal", "forms": ["voidsteel"]},
    "frostiron": {"display": "Frost Iron", "class": "metal", "forms": ["frostiron"]},
    "soulsteel": {"display": "Soulsteel", "class": "metal", "forms": ["soulsteel"]},
    "bloodsteel": {"display": "Bloodsteel", "class": "metal", "forms": ["bloodsteel"]},
    "sunsteel": {"display": "Sunsteel", "class": "metal", "forms": ["sunsteel"]},
    "starsteel": {"display": "Starsteel", "class": "metal", "forms": ["starsteel"]},
    "coldiron": {"display": "Cold Iron", "class": "metal", "forms": ["cold iron", "coldiron"]},
    "dragonshard": {"display": "Dragonshard", "class": "crystal/stone",
                     "forms": ["dragonshard", "dragonshards"]},
    "silversteel": {"display": "Silversteel", "class": "metal", "forms": ["silversteel"]},
    "moonsteel": {"display": "Moonsteel", "class": "metal", "forms": ["moonsteel"]},
}
NAMED_FORM_TO_KEY = {}
for _k, _v in NAMED_MATERIALS.items():
    for _f in _v["forms"]:
        NAMED_FORM_TO_KEY[_f] = _k
_named_forms_sorted = sorted(NAMED_FORM_TO_KEY.keys(), key=len, reverse=True)
NAMED_ALT = "|".join(re.escape(f) for f in _named_forms_sorted)

# Known multi-word phrases that match the noun vocabulary but actually name an
# *item category* (Ioun Stone, Quaal's Feather Token, ...) or a generic idiom
# ("looking glass"), not an exotic crafting material. Dropped post-match.
EXCLUDE_KEYS = {
    "iounstone", "touchstone", "milestone", "keystone", "cornerstone", "tombstone",
    "gravestone", "headstone", "millstone", "capstone", "whetstone", "grindstone",
    "curbstone", "cobblestone", "lookingglass", "magnifyingglass", "quaalfeather",
    "feathertoken", "studdedleather", "solderingiron",
}

# Creatures whose name, if it appears as the qualifier, is recorded as
# material.source_creature. Not exhaustive -- common SRD/MM creatures plus
# generated dragon-colour/giant-type combinations.
_BASE_CREATURES = [
    "owlbear", "troll", "ogre", "orc", "goblin", "hobgoblin", "bugbear", "kobold", "gnoll",
    "lizardfolk", "yuan-ti", "troglodyte", "basilisk", "cockatrice", "chimera", "manticore",
    "griffon", "griffin", "hippogriff", "pegasus", "unicorn", "wyvern", "hydra", "naga", "lamia",
    "harpy", "siren", "merfolk", "kraken", "krakens", "leviathan", "tarrasque", "roc", "phoenix",
    "thunderbird", "yeti", "ettin", "cyclops", "minotaur", "satyr", "centaur", "displacer beast",
    "blink dog", "worg", "dire wolf", "winter wolf", "giant spider", "giant rat", "giant toad",
    "giant eagle", "giant owl", "phase spider", "umber hulk", "otyugh", "ankheg", "bulette",
    "remorhaz", "roper", "rust monster", "gelatinous cube", "carrion crawler", "shambling mound",
    "treant", "awakened tree", "awakened shrub", "ghoul", "ghast", "zombie", "skeleton", "wraith",
    "specter", "spectre", "wight", "mummy", "lich", "vampire", "werewolf", "werebear", "wereboar",
    "weretiger", "wereraven", "banshee", "revenant", "death knight", "demon", "devil", "imp",
    "quasit", "succubus", "incubus", "balor", "pit fiend", "erinyes", "hezrou", "glabrezu",
    "marilith", "vrock", "barlgura", "nalfeshnee", "dretch", "mane", "angel", "deva", "planetar",
    "solar", "archon", "couatl", "modron", "slaad", "githyanki", "githzerai", "mind flayer",
    "illithid", "beholder", "aboleth", "elder brain", "drow", "duergar", "svirfneblin", "kenku",
    "aarakocra", "tabaxi", "bullywug", "kuo-toa", "sahuagin", "triton", "dragon turtle", "behir",
    "chuul", "gibbering mouther", "intellect devourer", "mimic", "flumph", "sphinx", "androsphinx",
    "gynosphinx", "peryton", "medusa", "gorgon", "giant scorpion", "giant centipede", "giant wasp",
    "giant frog", "giant lizard", "giant crocodile", "giant shark", "giant octopus", "giant crab",
    "giant boar", "giant elk", "giant goat", "giant vulture", "pixie", "sprite", "dryad",
    "faerie dragon", "pseudodragon", "flameskull", "helmed horror", "animated armor",
    "will-o-wisp", "wendigo", "abomination", "horror", "abyssal wretch", "hell hound",
    "blood hawk", "axe beak", "boar", "elk", "stag", "bear", "wolf", "spider", "rat", "toad",
    "eagle", "owl", "hawk", "falcon", "raven", "crow", "vulture", "panther", "lion", "tiger",
    "leopard", "wolverine", "badger", "weasel", "fox", "deer", "bison", "buffalo", "rhinoceros",
    "elephant", "mammoth", "whale", "shark", "crocodile", "alligator", "snake", "serpent", "viper",
    "constrictor snake", "wyrm", "drake", "salamander", "fire snake", "steeder", "grung",
    "quaggoth", "myconid", "shrieker", "violet fungus", "ooze", "gray ooze", "black pudding",
    "ochre jelly", "ettercap", "spider swarm", "insect swarm", "locust swarm", "rat swarm",
    "giant wolf spider", "stirge", "gargoyle", "golem", "flesh golem", "stone golem", "iron golem",
    "clay golem", "homunculus", "nightmare", "dullahan", "ghost",
]
_GIANT_TYPES = ["hill", "stone", "frost", "fire", "cloud", "storm", "fomorian"]
_BASE_CREATURES += [f"{t} giant" for t in _GIANT_TYPES]
_DRAGON_COLORS = ["red", "blue", "green", "black", "white", "brass", "bronze", "copper", "gold", "silver"]
_BASE_CREATURES += [f"{c} dragon" for c in _DRAGON_COLORS]
_BASE_CREATURES += [f"{c} wyrmling" for c in _DRAGON_COLORS]
CREATURE_NAMES = set(_BASE_CREATURES)

# =====================================================================
# 2. Stopword vocabulary used to clean up captured qualifier phrases.
# Grouped by why each word is excluded; union forms ALL_STOPWORDS. These
# words get stripped from *candidate material qualifiers* -- they are not
# excluded from the text as a whole.
# =====================================================================
DETERMINERS_PRONOUNS = [
    "a", "an", "the", "this", "that", "these", "those", "some", "any", "your", "my", "his",
    "her", "their", "our", "its", "such", "said", "each", "every", "another", "one", "which",
    "what", "it", "he", "she", "they", "we", "i", "you",
]
MUNDANE_QUALITY_ADJ = [
    "old", "new", "worn", "plain", "simple", "basic", "fine", "finely", "crude", "cheap",
    "thick", "thin", "soft", "hard", "supple", "standard", "common", "mundane", "ordinary",
    "normal", "raw", "fresh", "dyed", "painted", "polished", "good", "high", "poor", "low",
    "quality", "genuine", "real", "true", "fancy", "rough", "smooth", "heavy", "light", "shiny",
    "dull", "pristine", "sturdy", "durable", "exotic", "rare", "special", "magical", "magic",
    "enchanted", "ornate", "decorative", "strange", "unusual", "nonmagical", "reinforced",
    "enhanced", "improved", "modified", "upgraded", "tempered", "hardened", "studded", "padded",
    "interlocking", "short", "long", "single", "composed", "unworked", "ferrous", "charged",
    "articulated", "hollow", "vulnerable", "resistant", "immune", "uncommon", "legendary",
    "artifact", "varies", "regular", "treated",
]
CONDITION_ADJ = [
    "torn", "tattered", "scuffed", "battered", "rusty", "rusted", "corroded", "bent", "chipped",
    "cracked", "broken", "damaged", "decayed", "moldy", "mouldy", "stained", "weathered",
    "singed", "burnt", "charred", "faded", "discolored", "discoloured", "notched", "dented",
    "scratched", "ratty", "threadbare", "frayed", "neat", "tidy",
]
SIZE_QUANTITY_WORDS = [
    "large", "small", "huge", "tiny", "medium", "extra", "many", "few", "several", "most", "all",
    "number", "numbers", "pair", "pairs", "unit", "units", "bundle", "bundles", "scrap", "scraps",
    "piece", "pieces", "strip", "strips", "bit", "bits", "patch", "patches", "bolt", "bolts",
    "sheet", "sheets", "block", "blocks", "chunk", "chunks", "lump", "lumps", "shard", "shards",
    "inch", "inches", "foot", "feet", "yard", "yards", "pound", "pounds", "ounce", "ounces",
    "mile", "miles", "lb", "lbs", "kg", "oz", "rarity",
]
AGE_SIZE_CREATURE_MODIFIERS = [
    "young", "adult", "ancient", "wyrmling", "juvenile", "elder", "newborn", "hatchling",
    "greater", "lesser", "baby",
]
PREPOSITIONS = [
    "to", "by", "from", "of", "using", "use", "used", "with", "out", "into", "onto",
    "throughout", "within", "among", "near", "across", "around", "beneath", "beside", "between",
    "behind", "above", "below", "inside", "outside", "towards", "toward", "against", "under",
    "over", "through", "in", "as",
]
CONJUNCTIONS_COPULA_MODALS = [
    "and", "or", "nor", "but", "is", "are", "was", "were", "be", "been", "being", "can", "could",
    "may", "might", "must", "will", "would", "shall", "should", "if", "unless", "when",
    "whenever", "where", "wherever", "once", "until", "since", "while", "whilst",
]
CRAFTING_VERBS = [
    "made", "make", "makes", "crafted", "craft", "forged", "forge", "carved", "carve", "woven",
    "weave", "wove", "wrought", "cured", "cure", "shaped", "shape", "hewn", "hew", "spun", "spin",
    "sewn", "sew", "stitched", "stitch", "tanned", "tan", "cast", "molded", "mold", "moulded",
    "mould", "smithed", "smith", "smelt", "smelts", "smelting", "smelted",
]
GENERIC_VERBS_GERUNDS = [
    "containing", "holding", "hold", "holds", "carrying", "wearing", "wears", "wore", "worn",
    "featuring", "including", "having", "have", "has", "bearing", "showing", "displaying",
    "covered", "wrapped", "lined", "trimmed", "adorned", "decorated", "inlaid", "set", "take",
    "takes", "taking", "took", "taken", "check", "checks", "checking", "checked", "slot", "slots",
    "slotted", "destroy", "destroys", "destroyed", "insert", "inserts", "inserted", "remove",
    "removes", "removed", "place", "places", "placed", "apply", "applies", "applied", "attach",
    "attaches", "attached", "embed", "embeds", "embedded", "gain", "gains", "gained", "grant",
    "grants", "granted", "provide", "provides", "provided", "unlock", "unlocks", "unlocked",
    "activate", "activates", "activated", "deal", "deals", "dealing", "turn", "turns", "turning",
    "turned", "gifted", "given", "donated", "offered", "become", "becomes", "becoming", "became",
    "causing", "cause", "causes", "seize", "seizes", "seizing", "seized", "grasp", "grasps",
    "grasping", "grasped", "net", "nets", "netting", "stow", "stows", "stowing", "stowed",
    "throw", "throws", "throwing", "thrown", "toss", "tosses", "tossing", "hurl", "hurls",
    "hurling", "fling", "flings", "flinging", "try", "tries", "trying", "tried", "store",
    "stores", "storing", "stored", "bound", "binding", "bonded", "own", "owning", "possessing",
    "wielding", "consisting", "consists",
]
ADVERBS = [
    "freely", "simply", "merely", "only", "just", "purely", "partly", "mostly", "entirely",
    "completely", "wholly", "immediately", "successfully", "quickly", "often", "sometimes",
    "usually", "typically", "generally", "commonly", "frequently", "rarely", "occasionally",
    "even", "other", "than",
]
GENERIC_PLACEHOLDER_NOUNS = [
    "object", "objects", "creature", "creatures", "thing", "things", "item", "items",
    "anything", "everything", "something", "material", "materials", "substance", "substances",
    "device", "devices", "armor", "armour", "weapon", "weapons", "shield", "shields", "target",
    "targets", "gear", "equipment", "tree", "trees", "plant", "plants", "wall", "walls", "type",
    "types",
]
ALL_STOPWORDS = set(
    DETERMINERS_PRONOUNS + MUNDANE_QUALITY_ADJ + CONDITION_ADJ + SIZE_QUANTITY_WORDS
    + AGE_SIZE_CREATURE_MODIFIERS + PREPOSITIONS + CONJUNCTIONS_COPULA_MODALS + CRAFTING_VERBS
    + GENERIC_VERBS_GERUNDS + ADVERBS + GENERIC_PLACEHOLDER_NOUNS
)
# Rarity/mundane-ness guard used only for the copula pattern ("X is a common
# metal" should NOT register X as an exotic material).
MUNDANE_GUARD = {"common", "ordinary", "mundane", "normal", "standard", "simple", "basic",
                  "plain", "average", "typical", "generic"}

SPELLING_UNIFY = {
    "mithril": "mithral", "mithrals": "mithral", "mithrils": "mithral",
    "adamantite": "adamantine", "adamantites": "adamantine", "adamant": "adamantine",
    "armour": "armor", "armours": "armor",
}
NEVER_SINGULARIZE = {"glass", "brass", "grass", "chaos", "bronze", "moss", "bliss", "gas",
                      "canvas", "lens", "crossbow"}

# =====================================================================
# 3. Base-item inference helpers
# =====================================================================
TYPE_CODE_MAP = {
    "M": "Melee Weapon", "R": "Ranged Weapon", "LA": "Light Armor", "MA": "Medium Armor",
    "HA": "Heavy Armor", "S": "Shield", "A": "Ammunition", "AF": "Ammunition", "RD": "Rod",
    "ST": "Staff", "WD": "Wand", "SCF": "Spellcasting Focus", "RG": "Ring", "P": "Potion",
    "SC": "Scroll", "G": "Adventuring Gear", "INS": "Instrument", "GS": "Gaming Set",
    "AT": "Artisan Tools", "T": "Tool", "TAH": "Tack and Harness", "MNT": "Mount",
    "VEH": "Vehicle", "SHP": "Ship", "TG": "Trade Good", "$": "Treasure", "EXP": "Explosive",
    "GEM": "Gem", "OTH": "Other", "FD": "Food and Drink", "TAT": "Tattoo", "CY": "Currency",
}
GEAR_SUFFIX_PHRASES = sorted([
    "chain shirt", "chain mail", "scale mail", "half plate", "splint armor", "splint mail",
    "studded leather", "plate armor", "plate mail", "ring mail", "banded mail", "padded armor",
    "breast plate", "hide armor",
], key=len, reverse=True)
GEAR_SUFFIX_WORDS = {
    "armor", "armour", "boots", "gloves", "gauntlets", "bracers", "bracer", "shield",
    "breastplate", "cloak", "cape", "mantle", "robe", "robes", "jerkin", "vest", "cap", "helm",
    "helmet", "belt", "bag", "pouch", "satchel", "whip", "sword", "dagger", "axe", "hammer",
    "mace", "spear", "bow", "arrow", "arrows", "quiver", "staff", "wand", "rod", "amulet",
    "necklace", "saddle", "harness", "cord", "rope", "strap", "sling", "sandals", "hood", "mask",
    "shirt", "pants", "trousers", "gown", "tunic", "coat", "jacket", "buckler", "targe",
    "greaves", "pauldrons", "vambraces", "girdle", "crown", "circlet", "ring", "orb", "lantern",
    "horn", "club", "flail", "maul", "pick", "trident", "glaive", "halberd", "lance", "net",
    "bolt", "bolts", "bottle", "flask", "vial", "case", "scabbard", "sheath",
}

# =====================================================================
# 4. Regexes
# =====================================================================
TAG_RE = re.compile(r"\{@(\w+)\s+([^{}]*?)\}")
HASH_TAG_RE = re.compile(r"\{#[^{}]*\}")
TOKEN = r"[A-Za-z][A-Za-z'\u2019-]*"
PUNCT_STRIP = ".,;:!?'\"\u2019"
POSSESSIVE_RE = re.compile(r"[\u2019']s$|s[\u2019']$")
NEXT_WORD_RE = re.compile(r"^\s*([A-Za-z']+)")
NEXT_WORD_REJECT = {"action", "actions"}

# <qualifier (1-3 words)><noun>
PATTERN1_RE = re.compile(rf"((?:{TOKEN}\s+){{1,3}})({NOUN_ALT})\b", re.IGNORECASE)
# <noun> of/from <qualifier (1-3 words)>
_BOUNDARY_WORDS = (
    "and|that|which|before|who|whose|in|to|for|when|then|while|during|unless|rather|found|used|"
    "taken|obtained|harvested|gathered|collected|discovered|near|within|inside|throughout|after|"
    "once|upon|living|dwelling|residing|slain|killed|hunted|on|at|but|or|so|as"
)
PATTERN2_RE = re.compile(
    rf"\b({NOUN_ALT})\s+(?:of|from)\s+((?:(?:a|an|the)\s+)?(?:{TOKEN}\s*){{1,3}}?)"
    rf"(?=[.,;:!?]|\s+(?:{_BOUNDARY_WORDS})\b|$)",
    re.IGNORECASE,
)
# <Subject> is/are/was/were (a/an/the) <0-3 filler> <noun>  (e.g. "Targath is a rare metal...")
PATTERN3_RE = re.compile(
    rf"(?:^|[.!?]\s+)([A-Z][A-Za-z'\u2019-]*(?:\s+[A-Z][A-Za-z'\u2019-]*){{0,2}})\s+(?:is|are|was|were)\s+"
    rf"((?:(?:an?|the)\s+)?(?:{TOKEN}\s+){{0,3}}?)({NOUN_ALT}|{NAMED_ALT})\b"
)
NAMED_RE = re.compile(rf"\b({NAMED_ALT})\b", re.IGNORECASE)
MADE_FROM_RE = re.compile(
    r"\b(?:made|crafted|forged|carved|woven|wrought|cured|shaped|hewn|spun|sewn|stitched|"
    r"tanned|cast|molded|moulded|smithed)\s+(?:out\s+of|from|of|using|with)\b",
    re.IGNORECASE,
)
MADE_FROM_PROXIMITY = 45  # max char gap between a made-from verb phrase and the match it qualifies

# Tags whose inner text is cross-reference/game-mechanical noise for MATERIAL
# scanning (spell/action names routinely contain material words, e.g. "Heat
# Metal", "{@action Hide}") and are stripped there, but are kept for the
# effects-text pass used to build effects_summary.
REFERENCE_TAGS = {
    "spell", "action", "item", "class", "subclass", "classfeature", "subclassfeature", "feat",
    "optfeature", "race", "subrace", "background", "deity", "vehicle", "vehicleupgrade",
    "disease", "variantrule", "table", "quickref", "filter", "recipe", "reward", "boon", "cult",
    "object", "hazard", "trap", "language", "deck", "card", "facility", "legroup", "creature",
}


# =====================================================================
# 5. JSON loading
# =====================================================================
def register_sources(meta, source_book):
    """Item records reference their source via EITHER the `abbreviation` or
    the `json` field inconsistently across brews (76% of brews in this corpus
    give them different values), so register the book info under both keys."""
    for src in (meta or {}).get("sources", []) or []:
        info = {
            "full": src.get("full") or src.get("abbreviation") or src.get("json"),
            "authors": ", ".join(src.get("authors") or []) or None,
            "url": src.get("url"),
        }
        for key in (src.get("abbreviation"), src.get("json")):
            if key and key not in source_book:
                source_book[key] = info


def _get(it, field):
    v = it.get(field)
    if v is None:
        v = (it.get("inherits") or {}).get(field)
    return v


def load_records():
    """Return (records, source_book). records is a list of dicts, deduplicated
    by (name.lower(), source) across every scanned directory/file."""
    source_book = {}
    records = []
    seen = set()
    for dname in SCAN_DIRS:
        for fp in sorted((HOMEBREW_ROOT / dname).glob("*.json")):
            with open(fp, encoding="utf-8") as f:
                data = json.load(f)
            register_sources(data.get("_meta"), source_book)
            file_sources = [s.get("abbreviation") or s.get("json")
                             for s in (data.get("_meta") or {}).get("sources", []) or []]
            file_default_source = file_sources[0] if file_sources else None
            rel = str(fp.relative_to(HOMEBREW_ROOT))
            for key in ("item", "baseitem", "magicvariant", "itemGroup"):
                for it in data.get(key) or []:
                    name = it.get("name")
                    if not name:
                        continue
                    source = _get(it, "source") or file_default_source
                    dedupe_key = (name.strip().lower(), source)
                    if dedupe_key in seen:
                        continue
                    seen.add(dedupe_key)
                    records.append({
                        "name": name,
                        "source": source,
                        "page": _get(it, "page"),
                        "rarity_raw": _get(it, "rarity"),
                        "type_raw": _get(it, "type"),
                        "entries_field": _get(it, "entries"),
                        "brew_file": rel,
                        "baseItem": it.get("baseItem"),
                        "bonusWeapon": it.get("bonusWeapon"),
                        "bonusAc": it.get("bonusAc"),
                        "resist": it.get("resist"),
                        "immune": it.get("immune"),
                        "vulnerable": it.get("vulnerable"),
                        "conditionImmune": it.get("conditionImmune"),
                        "charges": it.get("charges"),
                        "recharge": it.get("recharge"),
                        "reqAttune": it.get("reqAttune"),
                        "modifySpeed": it.get("modifySpeed"),
                        "ability": it.get("ability"),
                    })
    return records, source_book


# =====================================================================
# 6. Text flattening
# =====================================================================
def flatten_entries(obj, out):
    if obj is None:
        return
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, list):
        for x in obj:
            flatten_entries(x, out)
    elif isinstance(obj, dict):
        t = obj.get("type")
        if isinstance(obj.get("name"), str) and t in (
                "entries", "list", "section", "inset", "insetReadaloud", "options"):
            out.append(obj["name"])
        if "entries" in obj:
            flatten_entries(obj["entries"], out)
        if isinstance(obj.get("items"), list):
            for sub in obj["items"]:
                if isinstance(sub, str):
                    out.append(sub)
                elif isinstance(sub, dict):
                    if "entry" in sub:
                        flatten_entries(sub["entry"], out)
                    if "entries" in sub:
                        flatten_entries(sub["entries"], out)
                    if isinstance(sub.get("name"), str):
                        out.append(sub["name"])
        if "rows" in obj:
            flatten_entries(obj.get("rows"), out)


def _strip_tag_effects(m):
    tag, body = m.group(1), m.group(2)
    parts = body.split("|")
    if tag == "dc":
        return f"DC {parts[0].strip()}"
    return parts[0].strip()


def _strip_tag_material(m):
    tag, body = m.group(1).lower(), m.group(2)
    if tag in REFERENCE_TAGS:
        return " "
    parts = body.split("|")
    if tag == "dc":
        return f"DC {parts[0].strip()}"
    return parts[0].strip()


def build_record_texts(rec):
    """Populate rec with text_material (for pattern scanning, reference tags
    dropped), text_effects (for effects_summary, tags resolved to content) and
    tag-categorised lists used by the effects summary builder."""
    buf = []
    flatten_entries(rec["entries_field"], buf)
    raw = " ".join(buf)
    raw = HASH_TAG_RE.sub(" ", raw)
    rec["text_material"] = re.sub(r"\s+", " ", TAG_RE.sub(_strip_tag_material, raw)).strip()
    rec["text_effects"] = re.sub(r"\s+", " ", TAG_RE.sub(_strip_tag_effects, raw)).strip()
    rec["dmg_tags"] = [m.group(2).split("|")[0].strip() for m in TAG_RE.finditer(raw) if m.group(1) == "damage"]
    rec["cond_tags"] = [m.group(2).split("|")[0].strip() for m in TAG_RE.finditer(raw) if m.group(1) == "condition"]
    rec["spell_tags"] = [m.group(2).split("|")[0].strip() for m in TAG_RE.finditer(raw) if m.group(1) == "spell"]
    rec["dc_tags"] = [m.group(2).split("|")[0].strip() for m in TAG_RE.finditer(raw) if m.group(1) == "dc"]


# =====================================================================
# 7. Normalisation helpers
# =====================================================================
def singularize_word(w):
    lw = w.lower()
    if lw in NEVER_SINGULARIZE:
        return w
    if lw.endswith("'s") or lw.endswith("\u2019s"):
        w, lw = w[:-2], lw[:-2]
    elif lw.endswith("s'") or lw.endswith("s\u2019"):
        w, lw = w[:-2], lw[:-2]
    if lw in SPELLING_UNIFY:
        return SPELLING_UNIFY[lw]
    if lw.endswith("ies") and len(lw) > 4:
        return w[:-3] + "y"
    if lw.endswith("s") and not lw.endswith("ss") and not lw.endswith("us") and len(lw) > 3:
        return w[:-1]
    return w


def clean_qualifier_words(words):
    """Drop stopword tokens (wherever they appear) from a captured qualifier
    word list; returns [] if nothing material-identifying remains."""
    out = []
    for w in words:
        lw = w.lower().strip(PUNCT_STRIP)
        if not lw:
            continue
        lw_noposs = POSSESSIVE_RE.sub("", lw)
        if lw in ALL_STOPWORDS or lw_noposs in ALL_STOPWORDS:
            continue
        stripped = w.strip(PUNCT_STRIP)
        if stripped:
            out.append(stripped)
    return out


def norm_key(words):
    """Fully concatenated, singularised, spelling-unified key used both to
    group material rows and to compare against the handout material lists."""
    out = []
    for w in words:
        w2 = singularize_word(w)
        w2 = re.sub(r"[^A-Za-z0-9]", "", w2).lower()
        if w2:
            out.append(w2)
    return "".join(out)


def display_words(words):
    out = []
    for w in words:
        w2 = singularize_word(w)
        w2 = re.sub(r"[^A-Za-z0-9'-]", "", w2)
        if w2:
            out.append(w2[:1].upper() + w2[1:])
    return out


def find_creature(words):
    lw = [w.lower() for w in words]
    for n in (3, 2, 1):
        if len(lw) >= n:
            phrase = " ".join(lw[-n:])
            if phrase in CREATURE_NAMES:
                return phrase
    return None


def context_window(text, start, end, max_words=12):
    left = text[:start].split()
    right = text[end:].split()
    mid = text[start:end].split()
    n_side = max(0, (max_words - len(mid)) // 2)
    snippet = " ".join(left[-n_side:] + mid + right[:n_side])
    return snippet[:160]


def next_word_is_reject(text, pos):
    m = NEXT_WORD_RE.match(text[pos:pos + 20])
    return bool(m) and m.group(1).lower() in NEXT_WORD_REJECT


def titlecase(s):
    return " ".join((w[:1].upper() + w[1:]) if w else w for w in s.split(" "))


def find_gear_suffix(remainder):
    low = remainder.lower()
    for phrase in GEAR_SUFFIX_PHRASES:
        if low.startswith(phrase):
            return phrase
    first = low.split()[0].strip(PUNCT_STRIP) if low.split() else ""
    return first if first in GEAR_SUFFIX_WORDS else None


def infer_base_item(item_name, baseitem_raw, type_raw, name_match_info):
    """name_match_info: None, or (prefix_or_None, end_index_within_item_name)."""
    if baseitem_raw:
        return titlecase(baseitem_raw.split("|")[0].strip())
    if name_match_info:
        prefix, end = name_match_info
        remainder = item_name[end:].strip().lstrip(",;:- ")
        gear = find_gear_suffix(remainder) if remainder else None
        if gear:
            return f"{prefix} {titlecase(gear)}" if prefix else titlecase(gear)
    if type_raw:
        base_type = type_raw.split("|")[0]
        if base_type in TYPE_CODE_MAP:
            return TYPE_CODE_MAP[base_type]
    return None


RARITY_SYNONYMS = {
    "none": "none", "common": "common", "uncommon": "uncommon", "rare": "rare",
    "very rare": "very rare", "legendary": "legendary", "artifact": "artifact",
    "varies": "varies", "unknown": "unknown", "unknown (magic)": "unknown",
}


def normalize_rarity(raw):
    if raw is None:
        return "unknown"
    if isinstance(raw, dict):
        return "varies"
    key = str(raw).strip().lower()
    return RARITY_SYNONYMS.get(key, "varies" if key else "unknown")


# =====================================================================
# 8. Material scanning engine
# =====================================================================
def scan_item(rec):
    """Return a list of hit dicts for one item record: key, disp (word list),
    material_class, confidence, matched_text, creature, base_item."""
    name, text = rec["name"], rec["text_material"]
    name_key = norm_key(clean_qualifier_words(name.split()))
    hits = []

    def add(key, disp_words, cls, conf, matched_text, creature, name_match_info):
        if not key or key in EXCLUDE_KEYS:
            return
        base_item = infer_base_item(name, rec.get("baseItem"), rec.get("type_raw"), name_match_info)
        hits.append({
            "key": key, "disp": disp_words, "class": cls, "conf": conf,
            "matched_text": matched_text, "creature": creature, "base_item": base_item,
        })

    # ---- NAME scan (-> high confidence) ----
    for m in PATTERN1_RE.finditer(name):
        if next_word_is_reject(name, m.end()):
            continue
        canon_noun, cls = SUFFIX_NOUNS[m.group(2).lower()]
        qwords = clean_qualifier_words(m.group(1).split())
        if not qwords:
            continue
        key = norm_key(qwords + [canon_noun])
        add(key, display_words(qwords) + [canon_noun], cls, "high", name[:160],
            find_creature(qwords), (canon_noun, m.end()))
    for m in NAMED_RE.finditer(name):
        dkey = NAMED_FORM_TO_KEY[m.group(1).lower()]
        info = NAMED_MATERIALS[dkey]
        add(dkey, [info["display"]], info["class"], "high", name[:160], None, (None, m.end()))

    # ---- TEXT scan (-> medium if near a "made from"-style verb, else low) ----
    made_from_ends = [m.end() for m in MADE_FROM_RE.finditer(text)]

    def near_made_from(pos):
        return any(e <= pos and pos - e <= MADE_FROM_PROXIMITY for e in made_from_ends)

    for m in PATTERN1_RE.finditer(text):
        if next_word_is_reject(text, m.end()):
            continue
        canon_noun, cls = SUFFIX_NOUNS[m.group(2).lower()]
        qwords = clean_qualifier_words(m.group(1).split())
        if not qwords:
            continue
        key = norm_key(qwords + [canon_noun])
        conf = "medium" if near_made_from(m.start()) else "low"
        add(key, display_words(qwords) + [canon_noun], cls, conf,
            context_window(text, m.start(), m.end()), find_creature(qwords), None)

    for m in PATTERN2_RE.finditer(text):
        canon_noun, cls = SUFFIX_NOUNS[m.group(1).lower()]
        qraw = m.group(2).split()
        while qraw and qraw[0].lower() in DETERMINERS_PRONOUNS:
            qraw = qraw[1:]
        qwords = clean_qualifier_words(qraw)
        if not qwords:
            continue
        key = norm_key(qwords + [canon_noun])
        conf = "medium" if near_made_from(m.start()) else "low"
        add(key, display_words(qwords) + [canon_noun], cls, conf,
            context_window(text, m.start(), m.end()), find_creature(qwords), None)

    for m in NAMED_RE.finditer(text):
        dkey = NAMED_FORM_TO_KEY[m.group(1).lower()]
        info = NAMED_MATERIALS[dkey]
        conf = "medium" if near_made_from(m.start()) else "low"
        add(dkey, [info["display"]], info["class"], conf,
            context_window(text, m.start(), m.end()), None, None)

    # ---- Copula-definitional pattern ("Targath is a rare metal...") -> medium ----
    for m in PATTERN3_RE.finditer(text):
        filler = m.group(2) or ""
        if any(w.lower() in MUNDANE_GUARD for w in filler.split()):
            continue
        subj = clean_qualifier_words(m.group(1).split())
        if not subj:
            continue
        noun_surface = m.group(3).lower()
        if noun_surface in SUFFIX_NOUNS:
            cls = SUFFIX_NOUNS[noun_surface][1]
        else:
            dkey0 = NAMED_FORM_TO_KEY.get(noun_surface)
            if dkey0 is None:
                continue
            cls = NAMED_MATERIALS[dkey0]["class"]
        key = norm_key(subj)
        if key and (key in name_key or name_key in key):
            continue  # self-reference guard: subject just restates the item's own name
        add(key, display_words(subj), cls, "medium",
            context_window(text, m.start(), m.end()), find_creature(subj), None)

    # keep only the highest-confidence hit per material key for this item
    best = {}
    for h in hits:
        cur = best.get(h["key"])
        if cur is None or CONFIDENCE_RANK[h["conf"]] < CONFIDENCE_RANK[cur["conf"]]:
            best[h["key"]] = h
    return list(best.values())


# =====================================================================
# 9. Effects summary (concise paraphrase built from structured fields/tags,
# never verbatim source prose)
# =====================================================================
def _fmt_list_field(val, label):
    flat = []
    if isinstance(val, list):
        for v in val:
            if isinstance(v, str):
                flat.append(v)
            elif isinstance(v, dict):
                if "special" in v:
                    flat.append(str(v["special"]))
                else:
                    for kk in ("resist", "immune", "vulnerable", "conditionImmune"):
                        if isinstance(v.get(kk), list):
                            flat.extend(str(x) for x in v[kk])
    elif isinstance(val, str):
        flat.append(val)
    flat = flat[:4]
    return f"{label} {', '.join(flat)}" if flat else None


def build_effects_summary(rec):
    parts = []
    if rec.get("bonusWeapon"):
        parts.append(f"{rec['bonusWeapon']} weapon")
    if rec.get("bonusAc"):
        parts.append(f"{rec['bonusAc']} AC")

    dmg_tags = rec.get("dmg_tags") or []
    if dmg_tags:
        dice = dmg_tags[0]
        dtype_m = re.search(re.escape(dice) + r"\s+(\w+)\s+damage", rec.get("text_effects", ""), re.IGNORECASE)
        dtype = f" {dtype_m.group(1).lower()}" if dtype_m else ""
        parts.append(f"+{dice}{dtype} damage")

    for field, label in (("resist", "resist"), ("immune", "immune"),
                          ("vulnerable", "vulnerable"), ("conditionImmune", "cond.immune")):
        s = _fmt_list_field(rec.get(field), label)
        if s:
            parts.append(s)

    if rec.get("charges"):
        rc = rec.get("recharge")
        parts.append(f"{rec['charges']} charges/{rc}" if rc else f"{rec['charges']} charges")

    ra = rec.get("reqAttune")
    if ra is True:
        parts.append("attunement")
    elif isinstance(ra, str) and ra.strip():
        parts.append(f"attunement ({ra.strip()})")

    ms = rec.get("modifySpeed")
    if isinstance(ms, dict):
        for k, v in ms.items():
            amt = v.get("*") if isinstance(v, dict) else v
            if amt is None and isinstance(v, dict) and v:
                amt = next(iter(v.values()))
            if amt is not None:
                if k == "bonus":
                    parts.append(f"+{amt} ft speed")
                elif k == "equal":
                    parts.append(f"speed {amt} ft")
                else:
                    parts.append(f"speed {k} {amt}")
            break

    ab = rec.get("ability")
    if isinstance(ab, dict):
        bits = []
        for k, v in ab.items():
            if k == "choose":
                continue
            if isinstance(v, dict) and "amount" in v:
                bits.append(f"{k.title()} {v['amount']}")
            elif isinstance(v, (int, str)):
                bits.append(f"{k.title()} {v}")
        if bits:
            parts.append("sets " + ", ".join(bits[:3]))

    conds = rec.get("cond_tags") or []
    if conds:
        parts.append("inflicts: " + ", ".join(list(dict.fromkeys(c.lower() for c in conds))[:3]))
    spells = rec.get("spell_tags") or []
    if spells:
        parts.append("casts: " + ", ".join(list(dict.fromkeys(s.lower() for s in spells))[:3]))
    dcs = rec.get("dc_tags") or []
    if dcs:
        parts.append(f"DC {dcs[0]}")

    if not parts:
        return "No extractable mechanical effect (see book)."
    summary = "; ".join(parts)
    return summary if len(summary) <= 220 else summary[:217] + "..."


# =====================================================================
# 10. Handout cross-check (in_handouts flag)
# =====================================================================
HANDOUT_NAME_RE = re.compile(r"^\|\s*\*\*([^*]+)\*\*")


def handout_candidate_keys(raw_name):
    raw_name = raw_name.strip()
    paren_m = re.match(r"^(.*?)\s*\(([^)]+)\)\s*$", raw_name)
    candidates = [paren_m.group(1).strip(), paren_m.group(2).strip()] if paren_m else [raw_name]
    keys = set()
    for c in candidates:
        for part in c.split("/"):
            part = part.strip()
            if part:
                k = norm_key(part.split())
                if k:
                    keys.add(k)
    return keys


def load_handout_keys():
    keys = set()
    for fp in HANDOUT_FILES:
        if not fp.exists():
            continue
        with open(fp, encoding="utf-8") as f:
            for line in f:
                m = HANDOUT_NAME_RE.match(line)
                if m:
                    keys |= handout_candidate_keys(m.group(1))
    return keys


# =====================================================================
# 11. Aggregation
# =====================================================================
def aggregate(records, all_hits, handout_keys, source_book):
    by_key_disp = {}
    by_key_class = {}
    by_key_creature = Counter()
    by_key_creature_totals = {}
    by_key_rarity = {}
    by_key_conf = {}
    by_key_count = Counter()
    reference_rows = []

    for i, h in all_hits:
        rec = records[i]
        key = h["key"]
        by_key_count[key] += 1
        by_key_disp.setdefault(key, Counter())[" ".join(h["disp"])] += 1
        by_key_class.setdefault(key, h["class"])
        if h["creature"]:
            by_key_creature_totals.setdefault(key, Counter())[h["creature"]] += 1
        rarity = normalize_rarity(rec["rarity_raw"])
        by_key_rarity.setdefault(key, Counter())[rarity] += 1
        by_key_conf.setdefault(key, Counter())[h["conf"]] += 1

        source_abbrev = rec["source"]
        book = (source_book.get(source_abbrev) or {}).get("full") or source_abbrev
        item_type = (rec["type_raw"].split("|")[0] if rec["type_raw"] else None)
        in_handout = 1 if key in handout_keys else 0

        reference_rows.append({
            "material_key": key,
            "item_name": rec["name"],
            "source_abbrev": source_abbrev,
            "book": book,
            "page": rec["page"],
            "brew_file": rec["brew_file"],
            "rarity": rarity,
            "item_type": item_type,
            "base_item": h["base_item"],
            "matched_text": h["matched_text"],
            "effects_summary": build_effects_summary(rec),
            "confidence": h["conf"],
            "in_handouts": in_handout,
        })

    material_rows = []
    display_name_by_key = {}
    for key, count in by_key_count.items():
        disp_name = by_key_disp[key].most_common(1)[0][0]
        display_name_by_key[key] = disp_name
        creature = None
        if key in by_key_creature_totals:
            creature = by_key_creature_totals[key].most_common(1)[0][0]
        rarity_spread = ", ".join(
            f"{r}:{by_key_rarity[key][r]}" for r in RARITY_ORDER if r in by_key_rarity[key]
        )
        confidence_spread = ", ".join(
            f"{c}:{by_key_conf[key][c]}" for c in CONFIDENCE_ORDER if c in by_key_conf[key]
        )
        material_rows.append({
            "name": disp_name,
            "material_class": by_key_class[key],
            "source_creature": creature,
            "item_count": count,
            "rarity_spread": rarity_spread,
            "confidence_spread": confidence_spread,
            "in_handouts": 1 if key in handout_keys else 0,
        })

    for row in reference_rows:
        row["material"] = display_name_by_key[row["material_key"]]
        del row["material_key"]

    return material_rows, reference_rows


# =====================================================================
# 12. SQLite output
# =====================================================================
SCHEMA = """
CREATE TABLE source_book (
    source_abbrev TEXT PRIMARY KEY,
    book          TEXT NOT NULL,
    authors       TEXT,
    url           TEXT
);

CREATE TABLE material (
    name               TEXT PRIMARY KEY,
    material_class     TEXT NOT NULL,
    source_creature    TEXT,
    item_count         INTEGER NOT NULL,
    rarity_spread      TEXT,
    confidence_spread  TEXT,
    in_handouts        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE material_reference (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    material         TEXT NOT NULL REFERENCES material(name),
    item_name        TEXT NOT NULL,
    source_abbrev    TEXT,
    book             TEXT,
    page             INTEGER,
    brew_file        TEXT NOT NULL,
    rarity           TEXT,
    item_type        TEXT,
    base_item        TEXT,
    matched_text     TEXT,
    effects_summary  TEXT,
    confidence       TEXT NOT NULL,
    in_handouts      INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX idx_material_reference_material ON material_reference(material);
CREATE INDEX idx_material_reference_item ON material_reference(item_name);
CREATE INDEX idx_material_class ON material(material_class);
"""


def write_db(material_rows, reference_rows, source_book):
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)

    conn.executemany(
        "INSERT INTO source_book (source_abbrev, book, authors, url) VALUES (?,?,?,?)",
        [(abbr, info["full"], info["authors"], info["url"]) for abbr, info in source_book.items()],
    )
    conn.executemany(
        "INSERT INTO material (name, material_class, source_creature, item_count, "
        "rarity_spread, confidence_spread, in_handouts) VALUES (?,?,?,?,?,?,?)",
        [(r["name"], r["material_class"], r["source_creature"], r["item_count"],
          r["rarity_spread"], r["confidence_spread"], r["in_handouts"]) for r in material_rows],
    )
    conn.executemany(
        "INSERT INTO material_reference (material, item_name, source_abbrev, book, page, "
        "brew_file, rarity, item_type, base_item, matched_text, effects_summary, confidence, "
        "in_handouts) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(r["material"], r["item_name"], r["source_abbrev"], r["book"], r["page"],
          r["brew_file"], r["rarity"], r["item_type"], r["base_item"], r["matched_text"],
          r["effects_summary"], r["confidence"], r["in_handouts"]) for r in reference_rows],
    )
    conn.commit()
    conn.close()


# =====================================================================
# 13. Main
# =====================================================================
def main():
    print("Loading homebrew JSON files...")
    records, source_book = load_records()
    print(f"  {len(records)} unique item-like records across {len(source_book)} sources")

    print("Building scan text...")
    for r in records:
        build_record_texts(r)

    print("Scanning for material candidates...")
    all_hits = []
    for i, r in enumerate(records):
        for h in scan_item(r):
            all_hits.append((i, h))
    print(f"  {len(all_hits)} candidate (item, material) pairs")

    print("Loading handout material names for in_handouts cross-check...")
    handout_keys = load_handout_keys()
    print(f"  {len(handout_keys)} normalised handout material keys")

    print("Aggregating material / material_reference rows...")
    material_rows, reference_rows = aggregate(records, all_hits, handout_keys, source_book)
    print(f"  {len(material_rows)} distinct materials, {len(reference_rows)} reference rows")

    print(f"Writing {DB_PATH} ...")
    write_db(material_rows, reference_rows, source_book)

    conf_counter = Counter(r["confidence"] for r in reference_rows)
    print("\nConfidence distribution:", dict(conf_counter))
    print("\nTop 30 materials by item count:")
    for r in sorted(material_rows, key=lambda x: -x["item_count"])[:30]:
        print(f"  {r['item_count']:4d}  {r['name']:30s} class={r['material_class']:14s} "
              f"creature={r['source_creature']} in_handouts={r['in_handouts']}")
    print("\nDone.")


if __name__ == "__main__":
    main()
