#!/usr/bin/env python3
"""
Supersede candidate detector — deterministic contradiction scan across cards.

Finds cards about the SAME entity that assert DIFFERENT values for a key field
(company, role, status, phone, handle, …). These are the "stacked contradiction"
that silent grep-recall surfaces as conflicting facts. This pass only REPORTS
(dry-run, like dedup.py) — the nightly LLM rollup reads the report and resolves
(rewrite current value + move old to ## History, per dbrain-processor rules).

  python3 supersede.py <vault-dir> [--apply] [--verbose]

Default: dry-run → writes .graph/supersede-candidates.json + prints a summary.
--apply: additionally stamps the OLDER card status=superseded + superseded_by pointer
         (conservative: only when exactly 2 cards and a clear newer-by-date winner).

No LLM. Reuses common.py (schema, frontmatter, duplicate grouping) as single source of truth.
"""
import json
import sys
from pathlib import Path

from common import (
    load_schema,
    parse_frontmatter,
    write_frontmatter,
    collect_duplicate_groups,
)

# Поля, где разные значения у одной сущности = противоречие (а не обогащение).
CONFLICT_FIELDS = ["company", "role", "status", "handle", "platform", "phone", "email", "title"]


def _card_date(fields: dict) -> str:
    # Свежесть карточки: updated > created > last_accessed. Для выбора «актуальной».
    return fields.get("updated") or fields.get("created") or fields.get("last_accessed") or ""


def scan(vault_dir: Path, schema: dict):
    groups = collect_duplicate_groups(vault_dir, schema)
    candidates = []
    for paths in groups.values():
        if len(paths) < 2:
            continue
        cards = []
        for rp in paths:  # rp — vault-относительный путь из collect_duplicate_groups
            try:
                fields = parse_frontmatter((vault_dir / rp).read_text(encoding="utf-8"))[0]
            except Exception:
                continue
            cards.append({"path": rp, "fields": fields})
        if len(cards) < 2:
            continue
        conflicts = {}
        for f in CONFLICT_FIELDS:
            vals = {}
            for c in cards:
                v = str(c["fields"].get(f, "")).strip()
                if v:
                    vals.setdefault(v, []).append(c["path"])
            if len(vals) > 1:  # одно поле, разные значения у одной сущности
                conflicts[f] = vals
        if conflicts:
            # «Актуальная» карточка — самая свежая по дате; остальные кандидаты на supersede.
            ordered = sorted(cards, key=lambda c: _card_date(c["fields"]), reverse=True)
            candidates.append(
                {
                    "entity": ordered[0]["path"].split("/")[-1].replace(".md", ""),
                    "current": ordered[0]["path"],
                    "superseded_candidates": [c["path"] for c in ordered[1:]],
                    "conflicts": conflicts,
                }
            )
    return candidates


def apply_supersede(vault_dir: Path, candidates: list) -> int:
    """Консервативно: только группы из ровно 2 карточек с явным более свежим победителем."""
    changed = 0
    for cand in candidates:
        if len(cand["superseded_candidates"]) != 1:
            continue
        old_rel = cand["superseded_candidates"][0]
        cur_rel = cand["current"]
        old_path = vault_dir / old_rel
        try:
            fields, body, lines = parse_frontmatter(old_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if fields.get("status") == "superseded":
            continue
        fields["status"] = "superseded"
        fields["superseded_by"] = f"[[{cur_rel.replace('.md', '')}]]"
        new_fm = write_frontmatter(fields, lines)
        old_path.write_text(f"---\n{new_fm}\n---\n{body}", encoding="utf-8")
        changed += 1
    return changed


def main():
    args = sys.argv[1:]
    if not args:
        print("Usage: supersede.py <vault-dir> [--apply] [--verbose]", file=sys.stderr)
        sys.exit(1)
    vault_dir = Path(args[0])
    apply = "--apply" in args
    verbose = "--verbose" in args
    schema = load_schema(vault_dir / ".claude" / "skills" / "autograph" / "schema.json")

    candidates = scan(vault_dir, schema)

    # Отчёт для ночного rollup.
    graph_dir = vault_dir / ".graph"
    graph_dir.mkdir(exist_ok=True)
    (graph_dir / "supersede-candidates.json").write_text(
        json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"supersede: {len(candidates)} conflict group(s) across same-entity cards")
    if verbose:
        for c in candidates:
            print(f"  ⚠ {c['entity']}: current={c['current']} | fields={list(c['conflicts'])}")

    if apply:
        n = apply_supersede(vault_dir, candidates)
        print(f"supersede: applied status=superseded to {n} card(s)")

    sys.exit(0)


if __name__ == "__main__":
    main()
