#!/usr/bin/env bash
# Validate 5etools-format JSON (book/entity data) against our LOCALLY PATCHED copy of
# the homebrew JSON schema bundled with the `5etools-utils` npm package.
#
# Why patched, not the stock "brew" schema: the stock schema's `_meta.sources[].json`
# field intentionally forbids official 5etools source codes (DMG, PHB, MM, ...) to
# stop *new third-party homebrew* from squatting on a real sourcebook's code — but our
# project deliberately reuses those official codes (per ref/5etools/schema-notes.md),
# since we're converting the official books themselves. `patch-schema.mjs` copies the
# stock "brew" schema and relaxes only that one field (to the same, less-restrictive
# definition the upstream "site" schema mode already uses for it) — every other brew
# convention (e.g. spell.classes) is left intact. Why not just use "site" mode
# wholesale: it's stricter in OTHER ways that reject legitimate brew-style fields our
# schema-notes.md documents (e.g. it rejects spell.classes.fromClassList entirely).
#
# Usage:
#   scripts/books/validate.sh <file.json>
#   scripts/books/validate.sh <directory>
#
# Validates every *.json file found (recursively, excluding index.json) and
# prints a pass/fail line per file plus a final summary. Exits non-zero if
# any file fails schema validation.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TOOLING_DIR="$REPO_ROOT/ref/5etools/tooling"
VALIDATOR_SCRIPT="$TOOLING_DIR/validate-json.mjs"
PATCH_SCRIPT="$TOOLING_DIR/patch-schema.mjs"
SCHEMA_PATCHED_DIR="$TOOLING_DIR/schema-patched"

if [[ ! -d "$TOOLING_DIR/node_modules/5etools-utils" ]]; then
	echo "error: 5etools-utils not installed in $TOOLING_DIR" >&2
	echo "       run: (cd ref/5etools/tooling && npm install)" >&2
	exit 2
fi

if [[ ! -f "$VALIDATOR_SCRIPT" ]]; then
	echo "error: validator not found at $VALIDATOR_SCRIPT" >&2
	exit 2
fi

# Regenerate the patched schema if missing (e.g. first run after a fresh `npm install`).
if [[ ! -d "$SCHEMA_PATCHED_DIR" ]]; then
	echo "Patched schema not found — generating it now..." >&2
	(cd "$TOOLING_DIR" && node "$PATCH_SCRIPT")
fi


if [[ $# -ne 1 ]]; then
	echo "usage: $0 <file-or-dir>" >&2
	exit 2
fi

TARGET="$1"

if [[ ! -e "$TARGET" ]]; then
	echo "error: no such file or directory: $TARGET" >&2
	exit 2
fi

# Collect the list of files to validate.
FILES=()
if [[ -f "$TARGET" ]]; then
	FILES=("$TARGET")
elif [[ -d "$TARGET" ]]; then
	while IFS= read -r -d '' f; do
		FILES+=("$f")
	done < <(find "$TARGET" -type f -name '*.json' ! -name 'index.json' -print0 | sort -z)
fi

if [[ ${#FILES[@]} -eq 0 ]]; then
	echo "error: no .json files found under $TARGET" >&2
	exit 2
fi

PASS_COUNT=0
FAIL_COUNT=0
FAILED_FILES=()

for f in "${FILES[@]}"; do
	# Resolve to an absolute path so it works regardless of cwd.
	if [[ "$f" = /* ]]; then
		ABS_F="$f"
	else
		ABS_F="$REPO_ROOT/$f"
	fi

	echo "----------------------------------------------------------------------"
	echo "Validating: $f"

	TMP_OUT="$(mktemp)"
	if (cd "$TOOLING_DIR" && node "$VALIDATOR_SCRIPT" "$ABS_F" > "$TMP_OUT" 2>&1); then
		PASS_COUNT=$((PASS_COUNT + 1))
		echo "PASS: $f"
	else
		FAIL_COUNT=$((FAIL_COUNT + 1))
		FAILED_FILES+=("$f")
		echo "FAIL: $f"
		awk '/^\[/{p=1} p{print} /^Schema test failed/{exit}' "$TMP_OUT"
	fi
	rm -f "$TMP_OUT"
done

echo "========================================================================"
echo "Summary: $PASS_COUNT passed, $FAIL_COUNT failed (of ${#FILES[@]} file(s))"

if [[ $FAIL_COUNT -gt 0 ]]; then
	echo "Failed files:"
	for f in "${FAILED_FILES[@]}"; do
		echo "  - $f"
	done
	exit 1
fi

exit 0
