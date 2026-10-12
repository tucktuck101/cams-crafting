# cams-crafting

Markdown notes and handouts for a D&D campaign's magical crafting materials.

## Generating new materials with ChatGPT

Paste this into ChatGPT (web browsing enabled):

> Read https://raw.githubusercontent.com/tucktuck101/cams-crafting/main/MATERIAL_GENERATOR_PROMPT.md and follow it to help me design new crafting materials.

The prompt points ChatGPT at the rules, the handouts and the reference exports below.

## Files

- **Handouts (canon):** `ores-and-ingots.md`, `woods-and-branches.md`, `Hides-and-leather.md`, `material-rarity-preface.md`
- **Rules:** `MATERIAL_CREATION_RULES.md`
- **Reference exports for ChatGPT:** `reference/` (Markdown views of the databases)
- **Databases:** `data/effects.db`, `data/base_items.db`, `data/material_candidates.db` (built from the 5etools homebrew repository)
- **Scripts:** `scripts/` rebuilds the databases and the `reference/` exports

After editing a handout or rebuilding a database, refresh the exports:

```
python3 scripts/export_reference_md.py
```
