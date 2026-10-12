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
        label = f"{form}: {effect_name or '—'}"
        if category:
            label += f" [{category}{' / ' + subtype if subtype else ''}{' / ' + trigger if trigger else ''}]"
        atoms[name].append(label)

    rows = []
    for name, handout, rarity, modifier, gold in effects.execute(
        "SELECT name, handout, rarity, difficulty_modifier, gold_cost FROM handout_material ORDER BY material_id"
    ):
        rows.append((name, handout_kind(handout), rarity, modifier, gold, "<br>".join(dict.fromkeys(atoms[name]))))

    body = [
        "# Existing Materials (current canon)",
        "",
        "Generated from the handouts by `scripts/export_reference_md.py`. The handouts themselves are the",
        "authoritative source; this file is a compact fingerprint of each material so new designs can be",
        "checked for duplication. Effect tags are `[category / subtype / trigger]`.",
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

    groups = defaultdict(list)
    for effect_id, category, subtype, trigger, count, magnitude, rarities in effects.execute(
        """SELECT effect_id, category, subtype, trigger, item_count, magnitude_summary, rarity_counts
           FROM effect WHERE item_count >= ? ORDER BY category, item_count DESC""",
        (MIN_PATTERN_ITEMS,),
    ):
        groups[category].append(
            (subtype, trigger, count, magnitude, rarity_counts(rarities), ", ".join(sorted(used_by.get(effect_id, ()))))
        )

    body = [
        "# Effect Patterns in Homebrew Magic Items",
        "",
        f"Deduplicated mechanical effects found on ~21,000 homebrew items (patterns seen on at least {MIN_PATTERN_ITEMS} items).",
        "Use the rarity counts as a balance benchmark: they show at which rarities each kind of effect usually appears.",
        "**Used by existing materials** lists canon materials that already use the pattern; avoid making a new",
        "material whose signature mechanic repeats one of these.",
        "Magnitudes are coarse (all dice sizes for a pattern are pooled).",
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
    for material, item, book, page in candidates.execute(
        """SELECT material, item_name, book, page FROM material_reference
           WHERE confidence IN ('high', 'medium')
           ORDER BY material, confidence = 'high' DESC, id"""
    ):
        if material not in examples:
            examples[material] = f"{item} ({book}{', p. ' + str(page) if page else ''})"

    groups = defaultdict(list)
    for name, cls, creature, count, in_handouts, rarity, conf, price in candidates.execute(
        """SELECT m.name, m.material_class, m.source_creature, m.item_count, m.in_handouts,
                  i.indicative_rarity, i.indicative_confidence, i.suggested_price_gp
           FROM material m JOIN material_indicative i ON i.material = m.name
           ORDER BY m.material_class, m.name"""
    ):
        groups[cls].append(
            (name, creature, rarity, conf, price, count, "yes" if in_handouts else "", examples.get(name))
        )

    body = [
        "# Material Candidates from Homebrew",
        "",
        "Materials mentioned by name or by an explicit \"made from\" phrase in homebrew items.",
        "**Indicative rarity is a model estimate, not a decision**: it was produced by a judge model calibrated",
        "on the existing materials (82% exact on those). Confidence reflects how close the estimate sits to a",
        "rarity boundary and whether descriptive text was found. Suggested price is per unit (ingot, branch,",
        "leather) using the handout price bands. Use this list for inspiration and to avoid unknowingly copying",
        "an existing homebrew material; `In handouts` marks overlap with canon.",
        "",
    ]
    total = 0
    for cls in sorted(groups):
        body += [f"## {cls}", "", table(
            ["Material", "Source creature", "Indicative rarity", "Confidence", "Suggested price (gp)", "Items", "In handouts", "Example item"],
            groups[cls],
        ), ""]
        total += len(groups[cls])
    (OUT / "material-candidates.md").write_text("\n".join(body))
    return total


def export_base_items(base):
    groups = defaultdict(lambda: defaultdict(set))
    for category, hint, name in base.execute(
        """SELECT category, COALESCE(primary_material_hint, 'unknown'), item_name FROM base_items
           WHERE category IN ('weapon', 'armor', 'shield', 'focus', 'ammunition')"""
    ):
        groups[category][hint].add(name)

    body = [
        "# Base Items",
        "",
        "Mundane templates that materials can be applied to, from homebrew `baseitem` entries and no-rarity items,",
        "grouped by category and likely primary material. Names only; full stats are in `data/base_items.db`.",
        "",
    ]
    total = 0
    for category in ("weapon", "armor", "shield", "focus", "ammunition"):
        body += [f"## {category}", ""]
        for hint in sorted(groups[category]):
            names = sorted(groups[category][hint], key=str.lower)
            total += len(names)
            body += [f"**{hint}** ({len(names)}): " + ", ".join(names), ""]
    (OUT / "base-items.md").write_text("\n".join(body))
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
