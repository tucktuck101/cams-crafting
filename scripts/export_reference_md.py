#!/usr/bin/env python3
"""Export the SQLite reference databases in data/ to Markdown files in reference/.

ChatGPT (and other web assistants) cannot open SQLite files from a URL, so the
generator prompt points at these Markdown exports instead. Re-run this script
after rebuilding any database or editing the handouts:

    python3 scripts/export_reference_md.py
"""
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "reference"
RARITIES = ["common", "uncommon", "rare", "very rare", "legendary", "artifact"]
MIN_PATTERN_ITEMS = 5
# Subtypes produced by extraction mistakes (e.g. "spell granted / the").
JUNK_SUBTYPES = {"the", "a", "an", "and", "or", "of", "this", "that", "it", "its", "your", "you"}
# Leading words that mark an extracted phrase rather than a material name (e.g. "Either Leather").
JUNK_MATERIAL_PREFIXES = {"either", "any", "each", "every", "other", "some", "the", "a", "an", "your", "its", "their",
                          "this", "that", "spiked", "worn", "studded", "padded", "plain", "simple", "ordinary"}
PRICED_CLASSES = {"metal", "wood"}


def cell(value):
    if value is None or value == "":
        return "—"
    return str(value).replace("|", "\\|").replace("\n", " ")


def table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines += ["| " + " | ".join(cell(v) for v in row) + " |" for row in rows]
    return "\n".join(lines)


def rarity_counts(raw):
    counts = json.loads(raw or "{}")
    return ", ".join(f"{r} {counts[r]}" for r in RARITIES if counts.get(r))


def handout_kind(handout):
    if "wood" in handout:
        return "wood"
    if "ore" in handout:
        return "metal"
    return "leather"


def export_existing_materials(effects):
    atoms = defaultdict(list)
    for name, form, effect_name, category, subtype, trigger in effects.execute(
        """SELECT m.name, f.form, f.effect_name, a.category, a.subtype, a.trigger
           FROM handout_material m
           JOIN handout_material_form f USING (material_id)
           LEFT JOIN handout_material_atom a USING (form_id)
           ORDER BY m.material_id, f.form_id, a.atom_id"""
    ):
        label = f"{form}: {effect_name or '(unnamed)'}"
        label += f" [{category}{' / ' + subtype if subtype else ''}{' / ' + trigger if trigger else ''}]" if category else " [untagged: read the handout]"
        atoms[name].append(label)

    rows = []
    for name, handout, rarity, modifier, gold in effects.execute(
        "SELECT name, handout, rarity, difficulty_modifier, gold_cost FROM handout_material ORDER BY material_id"
    ):
        rows.append((name, handout_kind(handout), rarity, modifier, gold, "<br>".join(dict.fromkeys(atoms[name]))))

    body = [
        "# Existing Materials (current canon)",
        "",
        "Generated from the handouts by `scripts/export_reference_md.py`. The handouts are the authoritative",
        "source. This file is a search aid: use the tags to find canon materials whose mechanics may overlap a new",
        "design, then compare against the full handout text before deciding whether the design is distinct.",
        "Effect tags are `[category / subtype / trigger]`.",
        "",
        table(["Material", "Kind", "Rarity", "Difficulty Modifier", "Gold Cost", "Effects by form"], rows),
        "",
    ]
    (OUT / "existing-materials.md").write_text("\n".join(body))
    return len(rows)


def export_effect_patterns(effects):
    used_by = defaultdict(set)
    for effect_id, name in effects.execute(
        """SELECT a.effect_id, m.name FROM handout_material_atom a
           JOIN handout_material_form f USING (form_id)
           JOIN handout_material m USING (material_id) WHERE a.effect_id IS NOT NULL"""
    ):
        used_by[effect_id].add(name)

    parsed = dict(effects.execute(
        "SELECT rarity, COUNT(*) FROM item_summary WHERE atom_count > 0 GROUP BY rarity"
    ).fetchall())
    scanned = effects.execute("SELECT COUNT(*) FROM item_summary").fetchone()[0]

    def rates(raw):
        counts = json.loads(raw or "{}")
        return ", ".join(
            f"{r} {counts[r]} ({100 * counts[r] / parsed[r]:.1f}%)" for r in RARITIES if counts.get(r) and parsed.get(r)
        )

    groups = defaultdict(list)
    for effect_id, category, subtype, trigger, count, magnitude, rarities in effects.execute(
        """SELECT effect_id, category, subtype, trigger, item_count, magnitude_summary, rarity_counts
           FROM effect WHERE item_count >= ? ORDER BY category, item_count DESC""",
        (MIN_PATTERN_ITEMS,),
    ):
        if subtype and len(subtype) < 3 or (subtype or "").lower() in JUNK_SUBTYPES:
            continue
        groups[category].append(
            (subtype, trigger, count, magnitude, rates(rarities), ", ".join(sorted(used_by.get(effect_id, ()))))
        )

    denominators = ", ".join(f"{r} {parsed[r]}" for r in RARITIES if parsed.get(r))
    body = [
        "# Effect Patterns in Homebrew Magic Items",
        "",
        f"{scanned:,} homebrew items were scanned; effects could be extracted from {sum(parsed.values()):,} of them.",
        f"Only patterns seen on at least {MIN_PATTERN_ITEMS} items are listed. Extraction is automatic and imperfect.",
        "",
        "**Items by rarity** shows how many items of each rarity have the effect, and in brackets the share of all",
        f"parsed items of that rarity ({denominators}). Use it as a rough balance benchmark only.",
        "Magnitudes are coarse: all dice sizes for a pattern are pooled.",
        "",
        "**Used by existing materials** lists canon materials tagged with the same pattern. It is a pointer for",
        "comparison, not a ban: a new material may share a tag if its actual effect (target, range, action, damage,",
        "duration, uses) and theme are clearly different.",
        "",
    ]
    total = 0
    for category in sorted(groups):
        body += [f"## {category}", "", table(
            ["Subtype", "Trigger", "Items", "Magnitudes", "Items by rarity", "Used by existing materials"], groups[category]
        ), ""]
        total += len(groups[category])
    (OUT / "effect-patterns.md").write_text("\n".join(body))
    return total


def export_material_candidates(candidates):
    examples = {}
    for material, item, book, page, summary in candidates.execute(
        """SELECT material, item_name, book, page, effects_summary FROM material_reference
           WHERE confidence IN ('high', 'medium')
           ORDER BY material, confidence = 'high' DESC, id"""
    ):
        if material not in examples:
            examples[material] = (f"{item} ({book}{', p. ' + str(page) if page else ''})", summary)

    groups = defaultdict(list)
    for name, cls, creature, count, in_handouts, rarity, conf, price in candidates.execute(
        """SELECT m.name, m.material_class, m.source_creature, m.item_count, m.in_handouts,
                  i.indicative_rarity, i.indicative_confidence, i.suggested_price_gp
           FROM material m JOIN material_indicative i ON i.material = m.name
           ORDER BY m.material_class, m.name"""
    ):
        if name.split()[0].lower() in JUNK_MATERIAL_PREFIXES:
            continue
        example, summary = examples.get(name, (None, None))
        groups[cls].append((
            name, creature, rarity, conf, price if cls in PRICED_CLASSES else None, count,
            "yes" if in_handouts else "", example, summary,
        ))

    total_materials = candidates.execute("SELECT COUNT(*) FROM material").fetchone()[0]
    body = [
        "# Material Candidates from Homebrew",
        "",
        f"A **selected, noisy subset**: {sum(len(v) for v in groups.values())} of {total_materials:,} material names",
        "extracted automatically from homebrew items, keeping only those named in an item's name or in an explicit",
        "\"made from\" phrase. Some entries are still extraction noise. Materials outside this list may exist.",
        "",
        "- **Indicative rarity is a model estimate, not a decision.** It was produced by a judge model calibrated on",
        "  the existing materials (82% exact on those). Confidence reflects how close the estimate sits to a rarity",
        "  boundary and whether descriptive text was found.",
        "- **Suggested price** is per unit, from the handout price bands. Only metals and woods have bands, so other",
        "  kinds show no price.",
        "- **Example item** and its effect summary are short and incomplete. Check the named book before claiming",
        "  a mechanical overlap or difference; otherwise compare names and themes only.",
        "- `In handouts` marks overlap with canon.",
        "",
    ]
    total = 0
    for cls in sorted(groups):
        body += [f"## {cls}", "", table(
            ["Material", "Source creature", "Indicative rarity", "Confidence", "Suggested price (gp)", "Items", "In handouts", "Example item", "Example effects (summary)"],
            groups[cls],
        ), ""]
        total += len(groups[cls])
    (OUT / "material-candidates.md").write_text("\n".join(body))
    return total


BASE_ITEM_VIEWS = {
    "weapon": ("Weapons", ["Name", "Material hint", "Weapon category", "Type", "Damage", "Properties", "Range", "Weight (lb)", "Cost (gp)", "Source"],
               "item_name, primary_material_hint, weapon_category, item_type_name, damage, properties, range, weight, value_gp"),
    "armor": ("Armour", ["Name", "Material hint", "Type", "AC", "Strength", "Stealth", "Weight (lb)", "Cost (gp)", "Source"],
              "item_name, primary_material_hint, item_type_name, ac, strength_req, "
              "CASE WHEN stealth_disadvantage THEN 'disadvantage' END, weight, value_gp"),
    "shield": ("Shields", ["Name", "Material hint", "AC bonus", "Strength", "Weight (lb)", "Cost (gp)", "Source"],
               "item_name, primary_material_hint, ac, strength_req, weight, value_gp"),
    "focus": ("Spellcasting Foci", ["Name", "Material hint", "Type", "Weight (lb)", "Cost (gp)", "Source"],
              "item_name, primary_material_hint, item_type_name, weight, value_gp"),
    "ammunition": ("Ammunition", ["Name", "Material hint", "Damage", "Weight (lb)", "Cost (gp)", "Source"],
                   "item_name, primary_material_hint, damage, weight, value_gp"),
}
# Spell components are listed as foci in the source data; they are not craftable base items.
COMPONENT_PREFIXES = ("pinch", "bit ", "bits ", "drop ", "piece", "pieces", "handful", "dab", "dollop", "cup ",
                      "either", "small ", "short ", "tiny", "three ", "two ", "seven ", "ashes", "square")


def export_base_items(base):
    folder = OUT / "base-items"
    folder.mkdir(exist_ok=True)
    intro = [
        "**Unreviewed** homebrew base items (`baseitem` entries and no-rarity items). The material hint is inferred",
        "automatically and is sometimes wrong. This is inspiration, not a list of allowed forms: the handout columns",
        "and the approved wooden-weapon list in the rules decide which forms a material can be made into.",
    ]
    index = ["# Base Items", "", *intro, "",
             "Items with identical stats in several books are listed once, with up to three sources.", "",
             "| Category | Items | File |", "| --- | --- | --- |"]
    total = 0
    for category, (title, headers, columns) in BASE_ITEM_VIEWS.items():
        merged = {}
        for row in base.execute(
            f"""SELECT {columns},
                       book || CASE WHEN page > 0 THEN ', p. ' || page ELSE '' END
                FROM base_items WHERE category = ? ORDER BY item_name COLLATE NOCASE, book""",
            (category,),
        ):
            stats, source = row[:-1], row[-1]
            if category == "focus" and (row[0].lower().startswith(COMPONENT_PREFIXES) or stats[-2:] == (None, None)):
                continue
            merged.setdefault((stats[0].lower(), *stats[1:]), [stats, []])[1].append(source)
        rows = []
        for stats, sources in merged.values():
            sources = list(dict.fromkeys(sources))
            shown = "; ".join(sources[:3]) + (f"; and {len(sources) - 3} more" if len(sources) > 3 else "")
            rows.append((*stats, shown))
        # Weapons are split by category and melee/ranged to keep each file small enough for web assistants.
        parts = defaultdict(list)
        for row in rows:
            if category != "weapon":
                parts[""].append(row)
                continue
            group = (row[2] or "").lower()
            group = group if group in ("simple", "martial") else "other"
            reach = "ranged" if "ranged" in (row[3] or "").lower() else "melee"
            parts[f"{group}-{reach}"].append(row)
        order = ["", "simple-melee", "simple-ranged", "martial-melee", "martial-ranged", "other-melee", "other-ranged"]
        for part in sorted(parts, key=order.index):
            part_rows = parts[part]
            name = f"{category}{'-' + part if part else ''}.md"
            label = f"{title}{' (' + part + ')' if part else ''}"
            (folder / name).write_text("\n".join([f"# {label}", "", *intro, "", table(headers, part_rows), ""]))
            index.append(f"| {label} | {len(part_rows)} | [base-items/{name}](base-items/{name}) |")
            total += len(part_rows)
    (OUT / "base-items.md").write_text("\n".join(index + [""]))
    return total


def main():
    OUT.mkdir(exist_ok=True)
    effects = sqlite3.connect(DATA / "effects.db")
    candidates = sqlite3.connect(DATA / "material_candidates.db")
    base = sqlite3.connect(DATA / "base_items.db")
    print("existing-materials.md:", export_existing_materials(effects), "materials")
    print("effect-patterns.md:", export_effect_patterns(effects), "patterns")
    print("material-candidates.md:", export_material_candidates(candidates), "materials")
    print("base-items.md:", export_base_items(base), "items")


if __name__ == "__main__":
    main()
