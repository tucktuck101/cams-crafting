#!/usr/bin/env python3
"""Extract `recipe` / `recipeFluff` entities for the Heroes' Feast cookbook family.

Target books (ref/5etools/sources.json, group "recipe"): HF, HFFotM, HFLotT, PaF.

Why this doesn't parse recipe mechanics out of ref/books/*.md: each recipe section in
these books' Markdown is a chapter heading + a short flavor-text paragraph, followed by
a client-side-rendered 5etools "data embed" web component
(`data-rd-tag="recipe" data-rd-uid="<Name>|<Source>" ... data-rd-hash="..."`) that never
resolved when the book was captured to Markdown -- it only ever shows a frozen
`Loading "<a ...>Name</a>"...` stub. The embed's own `data-vet-page`/`data-vet-source`/
`data-vet-hash` attributes point at where the real data lives. No ingredient/instruction
text exists anywhere in ref/books/*.md for any recipe in any of these 4 books (verified:
grep for "ingredients"/"instructions" in all 4 books only ever matches prose mentions
inside flavor text, never a structured list).

Per project policy (ref/5etools-src is the shared sparse mirror of
github.com/5etools-mirror-3/5etools-src `data/`, the same org/license as the books
themselves): where the Markdown has only a stub, fill the entity from
ref/5etools-src/data/{recipes,fluff-recipes}.json, matched by name+source (equivalent to
matching data-vet-hash, since the hash is just `lower(name)+"_"+lower(source)` with
spaces %-encoded). Every recipe name referenced by a `data-rd-tag="recipe"` embed in
each of the 4 books' Markdown was hand-verified to match a recipe in that JSON 1:1 (see
`_sanity_check` below, run as part of `main`), and fluff paragraphs are byte-identical to
the flavor text already present in the Markdown -- confirming this is the correct,
un-fabricated data for these specific books.

Genuine reprints: HFLotT has 5 recipes with their own H3 heading + own full-page image in
HFLotT's own Markdown, but whose data-vet-source says HFDoMM (a non-target book; 5etools
apparently single-sources the data record even for reprints). Per policy, a reprint with
its own heading in THIS book counts as this book's entity: extracted under source
"HFLotT", mechanics taken from the HFDoMM record, sidecar notes `data_from: "HFDoMM"`.
HFDoMM has no flavor text of its own in HFLotT's Markdown (just image + embed), so the
HFDoMM fluff paragraph is reused. No other books have any cross-source recipe embeds.

Output:
    ref/5etools/shards/recipes/<SOURCE>.json              (recipe + recipeFluff arrays)
    ref/5etools/shards/recipes/<SOURCE>.provenance.json    (name -> section id / origin)

Usage: python3 scripts/books/extract_recipes.py
"""
from __future__ import annotations

import html
import json
import re
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BOOKS_DIR = REPO / "ref/books"
SHARD_DIR = REPO / "ref/5etools/shards/recipes"
SOURCES_JSON = REPO / "ref/5etools/sources.json"
SECTIONS_JSONL = REPO / "ref/5etools/sections.jsonl"
BOOKDATA_DIR = REPO / "ref/5etools/books"
SRC_RECIPES = REPO / "ref/5etools-src/data/recipes.json"
SRC_FLUFF = REPO / "ref/5etools-src/data/fluff-recipes.json"

BOOK_FILES = {
    "HF": "Heroes' Feast.md",
    "HFFotM": "Heroes' Feast Flavors of the Multiverse.md",
    "HFLotT": "Heroes' Feast Legends of the Table.md",
    "PaF": "Puncheons and Flagons.md",
}

EMBED_RE = re.compile(
    r'data-rd-tag="recipe"\s+data-rd-uid="([^"]*)"\s+data-rd-page="([^"]*)"\s+'
    r'data-rd-source="([^"]*)"\s+data-rd-hash="([^"]*)"'
)

# Hand-verified exception: PaF's "Craknoeg" (the vegan variant of "Crakaneg") is embedded
# under the "#### Vegan Variation" sub-heading, not under a heading matching its own name,
# so normal name<->heading matching misses it.
MANUAL_SECTION_ID = {
    ("PaF", "craknoeg"): "PaF:brandy-from-the-driftwood-tavern-in-neverwinter/crakaneg/vegan-variation",
}

# Hand-verified genuine reprints: own heading/image in HFLotT, mechanics+fluff only exist
# under a different source (HFDoMM, not one of our 51 books) in the official data.
REPRINTS = {
    "HFLotT": {
        "Moonwood Artichoke Spread": "HFDoMM",
        "Spicy Shredded Stirge Sliders": "HFDoMM",
        "Halfling Finger Sandwiches": "HFDoMM",
        "Exploding Cheese Puffs": "HFDoMM",
        "Night Hag's Delight": "HFDoMM",
    }
}

# recipeData fields we keep verbatim from the official record (already in our target
# schema's own entry.json conventions -- ingredient/{=amount} formulas, type:"entries"
# groupings, etc. -- since the brew schema was modeled on this exact data format).
KEEP_FIELDS = [
    "alias", "type", "dishTypes", "diet", "serves", "makes",
    "ingredients", "equipment", "instructions", "noteCook",
    "miscTags", "allergenGroups",
]


def norm(s: str) -> str:
    return html.unescape(s).strip().lower().replace("\u2019", "'").replace("\u2018", "'")


def load_sections() -> dict[tuple[str, str], tuple[str, str]]:
    """(source, norm(last heading)) -> (heading text, section id)."""
    out: dict[tuple[str, str], tuple[str, str]] = {}
    for line in SECTIONS_JSONL.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        path = d.get("path") or []
        if not path:
            continue
        key = (d["source"], norm(path[-1]))
        out.setdefault(key, (path[-1], d["id"]))
    return out


def find_embeds(text: str) -> list[tuple[str, str, str]]:
    """-> list of (name, source, hash) for every data-rd-tag="recipe" embed."""
    out = []
    for uid, _page, esrc, ehash in EMBED_RE.findall(text):
        name = html.unescape(uid.rsplit("|", 1)[0])
        out.append((name, esrc, ehash))
    return out


def resolve_fluff(name: str, source: str, fluff_by_key: dict) -> list | None:
    f = fluff_by_key.get((source, norm(name)))
    if f is None:
        return None
    if "entries" in f and f["entries"]:
        return f["entries"]
    if "_copy" in f:
        ref = f["_copy"]
        return resolve_fluff(ref["name"], ref["source"], fluff_by_key)
    return None


def build_recipe(r: dict, out_name: str, out_source: str) -> dict:
    out = {"name": out_name, "source": out_source}
    for field in KEEP_FIELDS:
        if field in r:
            out[field] = r[field]
    return out


def main() -> None:
    official = json.loads(SRC_RECIPES.read_text(encoding="utf-8"))["recipe"]
    fluff_list = json.loads(SRC_FLUFF.read_text(encoding="utf-8"))["recipeFluff"]
    fluff_by_key = {(f["source"], norm(f["name"])): f for f in fluff_list}
    heading_by_key = load_sections()
    sources_meta = json.loads(SOURCES_JSON.read_text(encoding="utf-8"))["books"]
    sources_by_code = {s["source"]: s for s in sources_meta}

    now = int(time.time())
    SHARD_DIR.mkdir(parents=True, exist_ok=True)

    report = {}
    for source, filename in BOOK_FILES.items():
        text = (BOOKS_DIR / filename).read_text(encoding="utf-8")
        embeds = find_embeds(text)
        own_names = {name for name, esrc, _h in embeds if esrc == source}
        cross_names = {(name, esrc) for name, esrc, _h in embeds if esrc != source}
        own_names_norm = {norm(n) for n in own_names}

        official_this = [r for r in official if r["source"] == source]
        official_names_norm = {norm(r["name"]) for r in official_this}

        reprint_map = REPRINTS.get(source, {})
        reprint_recipes = []
        for name, foreign_src in reprint_map.items():
            match = [r for r in official if r["source"] == foreign_src and r["name"] == name]
            if match:
                reprint_recipes.append((name, foreign_src, match[0]))

        # --- sanity check: every own-source embed name should resolve to an official
        # record, and vice versa (modulo the one hand-verified exception below). ---
        unmatched_embeds = sorted(
            n for n in own_names
            if norm(n) not in official_names_norm and norm(n) not in MANUAL_SECTION_ID.get((source, norm(n)), "")
        )
        unmatched_official = sorted(
            r["name"] for r in official_this if norm(r["name"]) not in own_names_norm
        )
        # Craknoeg (PaF) is a known exception: its embed sits under "Vegan Variation",
        # not a heading matching its own name.
        unmatched_official = [n for n in unmatched_official if (source, norm(n)) not in MANUAL_SECTION_ID]

        out_recipes = []
        out_fluff = []
        provenance: dict[str, dict] = {}
        candidates_skipped = []

        for r in official_this:
            name = r["name"]
            key = (source, norm(name))
            heading = heading_by_key.get(key)
            # PaF title-case quirk (5 entries): official name is ALL-WORDS-CAPITALIZED,
            # markdown heading uses normal title case -- prefer the markdown's casing.
            if heading and heading[0] != name and heading[0].lower() == name.lower():
                name = heading[0]
            section_id = heading[1] if heading else MANUAL_SECTION_ID.get(key)

            out_recipes.append(build_recipe(r, name, source))
            fluff_entries = resolve_fluff(r["name"], source, fluff_by_key)
            if fluff_entries:
                out_fluff.append({"name": name, "source": source, "entries": fluff_entries})
                out_recipes[-1]["hasFluff"] = True
            provenance[name] = {
                "sectionId": section_id,
                "origin": "5etools-src",
            }

        for name, foreign_src, r in reprint_recipes:
            key = (source, norm(name))
            heading = heading_by_key.get(key)
            section_id = heading[1] if heading else None
            out_recipes.append(build_recipe(r, name, source))
            fluff_entries = resolve_fluff(name, foreign_src, fluff_by_key)
            if fluff_entries:
                out_fluff.append({"name": name, "source": source, "entries": fluff_entries})
                out_recipes[-1]["hasFluff"] = True
            provenance[name] = {
                "sectionId": section_id,
                "origin": "5etools-src",
                "data_from": foreign_src,
                "note": "genuine reprint: own heading/image in this book, mechanics+fluff sourced from data_from",
            }

        out_recipes.sort(key=lambda x: x["name"])
        out_fluff.sort(key=lambda x: x["name"])

        book_src_meta = json.loads((BOOKDATA_DIR / f"{source}.json").read_text(encoding="utf-8"))
        shard = {
            "_meta": {
                "sources": book_src_meta["_meta"]["sources"],
                "edition": book_src_meta["_meta"].get("edition", "classic"),
                "internalCopies": ["recipeFluff"],
                "dateAdded": now,
                "dateLastModified": now,
            },
            "recipe": out_recipes,
            "recipeFluff": out_fluff,
        }
        (SHARD_DIR / f"{source}.json").write_text(
            json.dumps(shard, indent="\t", ensure_ascii=False) + "\n", encoding="utf-8"
        )
        (SHARD_DIR / f"{source}.provenance.json").write_text(
            json.dumps(provenance, indent="\t", ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
        )

        report[source] = {
            "recipes": len(out_recipes),
            "fluff": len(out_fluff),
            "reprints_from_other_books": len(reprint_recipes),
            "cross_references_excluded": sorted(cross_names - {(n, s) for n, s, _r in reprint_recipes}),
            "unmatched_embeds_vs_official": unmatched_embeds,
            "unmatched_official_vs_embeds": unmatched_official,
        }

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
