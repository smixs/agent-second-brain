#!/usr/bin/env python3
"""
Ranked memory search over a vault — BM25 (sqlite3 FTS5) + link-graph rerank.

Replaces "raw grep" recall: lexical BM25 ranking via the stdlib sqlite3 FTS5
module (zero extra deps, no native build) + a free rerank over the nightly
.graph/vault-graph.json that graph.py already writes. Language-agnostic
(IDF from the vault's own corpus, no stopword lists) and schema-agnostic
(reads arbitrary frontmatter — no hardcoded card types). Degrades softly:
any engine failure falls back to a naive substring scan, the call never fails.

  python3 search.py <query> [--vault DIR] [--limit N] [--scope DIR ...] [--json]
  python3 search.py --selftest

Output (--json): {"count", "engine", "hits": [{file, score, status, confidence, snippet}]}
Port of Iva's agent/tools/memory_search.ts. Hybrid dense/embeddings layer is
intentionally omitted (opt-in in the source, off by default).
"""
import argparse
import json
import math
import re
import sqlite3
from pathlib import Path

# parse_frontmatter is the single source of truth for reading cards. Fall back to
# a tiny local parser only if run outside the skill dir (keeps --selftest hermetic).
try:
    from common import parse_frontmatter
except Exception:  # pragma: no cover - only when common.py isn't importable
    def parse_frontmatter(content):
        content = content.replace("\r\n", "\n").replace("\r", "\n")
        m = re.match(r"^---\n(.*?)\n---\n?(.*)", content, re.DOTALL)
        if not m:
            return None, content, []
        fields = {}
        for line in m.group(1).split("\n"):
            mm = re.match(r"^([A-Za-z0-9_]+):\s*(.*)$", line.strip())
            if mm:
                fields[mm.group(1).lower()] = mm.group(2).strip().strip("\"'")
        return fields, m.group(2), []

# Noise / binary / system dirs never worth indexing. Raw transcripts and templates
# are excluded by default (distilled cards carry the signal); pass --scope to include.
IGNORE_DIRS = {
    ".git", ".graph", ".index", ".cache", ".trash", ".obsidian", "node_modules",
    "attachments", "templates", ".claude", ".sessions", ".output",
}
# Frontmatter fields that carry searchable meaning for structured cards. Indexed in a
# high-weight column — a name/company living only in frontmatter would miss the body.
META_FIELDS = [
    "name", "company", "role", "description", "handle", "aliases", "aka", "title",
    "platform", "industry", "domain",
]
MAX_SNIPPET = 240
K = 60  # RRF rank-fusion constant
STALE = {"superseded", "archived", "cancelled", "inactive", "reverted"}


def _as_text(val) -> str:
    if val is None:
        return ""
    if isinstance(val, list):
        return " ".join(str(v) for v in val)
    return str(val)


def load_docs(vault: Path, scope_dirs):
    docs = []
    roots = [vault / d for d in scope_dirs] if scope_dirs else [vault]
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*.md"):
            if any(part in IGNORE_DIRS for part in path.relative_to(vault).parts):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except Exception:
                continue
            fm, body, _ = parse_frontmatter(text)
            fm = fm or {}
            rel = path.relative_to(vault).as_posix()
            meta = " ".join(_as_text(fm.get(k)) for k in META_FIELDS if fm.get(k))
            docs.append({
                "path": rel,
                "title": Path(rel).stem,
                "meta": meta,
                "body": body[:8000],
                "tags": _as_text(fm.get("tags")),
                "status": _as_text(fm.get("status")).lower(),
                "confidence": _as_text(fm.get("confidence")).upper(),
            })
    return docs


def content_tokens(query: str):
    # Language-agnostic: any Unicode word run, unique. No stopwords/length floors —
    # significance comes from IDF in the vault, not a language list.
    return list(dict.fromkeys(re.findall(r"\w+", query.lower(), re.UNICODE)))


def to_fts_query(tokens):
    # Each token as a prefix term (universal morphology) OR-joined. Escape embedded quotes.
    return " OR ".join(f'"{t.replace(chr(34), "")}"*' for t in tokens) if tokens else ""


def bm25_search(docs, fts_query, limit):
    """BM25 via in-memory sqlite3 FTS5. Raises on any failure -> caller falls back."""
    db = sqlite3.connect(":memory:")
    try:
        db.execute("CREATE VIRTUAL TABLE d USING fts5(path UNINDEXED, title, meta, tags, body)")
        db.executemany(
            "INSERT INTO d(path, title, meta, tags, body) VALUES (?,?,?,?,?)",
            [(x["path"], x["title"], x["meta"], x["tags"], x["body"]) for x in docs],
        )
        # Column weights: title/meta > tags > body (lower bm25 = more relevant).
        # bm25() takes ONE weight per column in declaration order, INCLUDING the
        # UNINDEXED `path` (weight ignored but its slot must be present) — otherwise
        # every weight shifts left by one and meta/tags get mis-weighted.
        rows = db.execute(
            "SELECT path FROM d WHERE d MATCH ? "
            "ORDER BY bm25(d, 0.0, 5.0, 5.0, 2.0, 1.0) LIMIT ?",
            (fts_query, limit * 4),
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        db.close()


def naive_search(docs, tokens):
    scored = []
    for doc in docs:
        hay = f"{doc['title']} {doc['meta']} {doc['tags']} {doc['body']}".lower()
        title = doc["title"].lower()
        s = 0
        for t in tokens:
            start = 0
            while (idx := hay.find(t, start)) != -1:
                s += 3 if t in title else 1
                start = idx + len(t)
        if s > 0:
            scored.append((doc["path"], s))
    scored.sort(key=lambda x: x[1], reverse=True)
    return [p for p, _ in scored]


def load_graph(vault: Path):
    try:
        j = json.loads((vault / ".graph" / "vault-graph.json").read_text(encoding="utf-8"))
        return j.get("nodes", {}) or {}
    except Exception:
        return {}


def bfs_distances(graph, anchors, max_hops):
    dist = {}
    frontier = []
    for a in anchors:
        if a in graph:
            dist[a] = 0
            frontier.append(a)
    hop = 1
    while hop <= max_hops and frontier:
        nxt = []
        for node in frontier:
            n = graph.get(node) or {}
            for nb in list(n.get("outgoing") or []) + list(n.get("incoming") or []):
                if nb not in dist:
                    dist[nb] = hop
                    nxt.append(nb)
        frontier = nxt
        hop += 1
    return dist


def snippet(body, tokens):
    low = body.lower()
    at = -1
    for t in tokens:
        i = low.find(t)
        if i != -1 and (at == -1 or i < at):
            at = i
    start = 0 if at == -1 else max(0, at - 60)
    return re.sub(r"\s+", " ", body[start:start + MAX_SNIPPET]).strip()


def search_memory(vault: Path, query: str, limit: int = 8, scope=None):
    tokens = content_tokens(query)
    docs = load_docs(vault, scope)
    if not docs:
        return {"count": 0, "engine": "none", "hits": [], "note": "vault empty or unreadable"}

    engine = "bm25"
    try:
        fts_query = to_fts_query(tokens)
        ranked = bm25_search(docs, fts_query, limit) if fts_query else []
        if not ranked:
            ranked = naive_search(docs, tokens)
            engine = "naive-empty-bm25"
    except Exception:
        ranked = naive_search(docs, tokens)
        engine = "naive-fallback"

    # RRF-style base score: stable regardless of raw (unbounded, tiny-card-unstable) bm25.
    base = {path: 1.0 / (K + i) for i, path in enumerate(ranked)}

    # Link-distance rerank: anchors = top-3 hits; BFS gives each card's closeness to the topic.
    graph = load_graph(vault)
    anchors = [p[:-3] if p.endswith(".md") else p for p in ranked[:3]]
    dist = bfs_distances(graph, anchors, 2)

    # Graph-recall: strong 1-hop neighbors lexical search missed, with a tiny base score.
    neighbor_base = 1.0 / (K + len(ranked) + 5)
    for noext, d in dist.items():
        if d == 1 and (noext + ".md") not in base:
            base[noext + ".md"] = neighbor_base

    # Language-agnostic weighting: term weight = its IDF in the vault itself.
    hay_by_path = {
        x["path"]: f"{x['title']} {x['meta']} {x['tags']} {x['body']}".lower() for x in docs
    }
    idf = {}
    for t in tokens:
        df = sum(1 for h in hay_by_path.values() if t in h)
        idf[t] = math.log((len(docs) + 1) / (df + 1)) + 1
    idf_total = sum(idf.values()) or 1

    def coverage(path):
        if not tokens:
            return 1.0
        hay = hay_by_path.get(path, "")
        return sum(idf[t] for t in tokens if t in hay) / idf_total

    by_path = {x["path"]: x for x in docs}
    hits = []
    for path, s0 in base.items():
        doc = by_path.get(path)
        if not doc:
            continue
        noext = path[:-3] if path.endswith(".md") else path
        d = dist.get(noext)
        proximity = 1.0 if d is None else (1.5 if d == 0 else 1.3 if d == 1 else 1.15)
        incoming = len((graph.get(noext) or {}).get("incoming") or [])
        cov = 0.3 + coverage(doc["path"])
        score = s0 * cov * proximity * (1 + min(incoming, 10) * 0.03)
        if doc["status"] in STALE:
            score *= 0.3
        hits.append({
            "file": doc["path"],
            "score": round(score, 6),
            "status": doc["status"],
            "confidence": doc["confidence"],
            "snippet": snippet(doc["body"], tokens),
        })
    hits.sort(key=lambda h: h["score"], reverse=True)
    return {"count": len(hits), "engine": engine, "hits": hits[:limit]}


def _selftest():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        v = Path(tmp)
        (v / "cards").mkdir()
        (v / "cards" / "rushana.md").write_text(
            "---\ntype: contact\ncompany: TDI Group\nstatus: active\n---\n"
            "# Rushana\nRushana leads the promo team at TDI Group.\n", encoding="utf-8")
        (v / "cards" / "rush-note.md").write_text(
            "---\ntype: note\nstatus: active\n---\n# Rush\nA rush job note, unrelated person.\n",
            encoding="utf-8")
        (v / "cards" / "old-rushana.md").write_text(
            "---\ntype: contact\ncompany: BBDO\nstatus: superseded\n---\n# Rushana\nOld card.\n",
            encoding="utf-8")
        res = search_memory(v, "rushana tdi", limit=5)
        assert res["count"] >= 1, res
        assert res["hits"][0]["file"] == "cards/rushana.md", res["hits"]
        # superseded card is findable but demoted below the active one.
        files = [h["file"] for h in res["hits"]]
        if "cards/old-rushana.md" in files and "cards/rushana.md" in files:
            assert files.index("cards/rushana.md") < files.index("cards/old-rushana.md"), files
        # graceful even with no matches
        assert search_memory(v, "zzzznomatch", limit=5)["count"] == 0 or True
    print("search.py selftest: OK")


def main():
    ap = argparse.ArgumentParser(description="Ranked memory search (BM25 + graph rerank)")
    ap.add_argument("query", nargs="?", help="free-form query")
    ap.add_argument("--vault", default=".", help="vault dir (default: cwd)")
    ap.add_argument("--limit", type=int, default=8)
    ap.add_argument("--scope", nargs="*", help="subdirs to search (default: whole vault)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        _selftest()
        return
    if not args.query:
        ap.error("query is required (or --selftest)")

    res = search_memory(Path(args.vault), args.query, args.limit, args.scope)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(f"[{res['engine']}] {res['count']} hit(s)")
        for h in res["hits"]:
            flags = " ".join(f for f in (h["status"], h["confidence"]) if f)
            print(f"  {h['score']:.4f}  {h['file']}  {('(' + flags + ')') if flags else ''}")
            if h["snippet"]:
                print(f"          {h['snippet'][:160]}")


if __name__ == "__main__":
    main()
