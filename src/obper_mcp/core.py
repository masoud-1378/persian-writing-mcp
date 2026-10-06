"""Shared vault logic for the obsidian-persian MCP server.

Stdlib only: safe to import from both the local stdio shim (which runs on the
pinned `mcp<2` venv) and the packaged server (which needs standalone fastmcp).
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parent

K1, B = 1.2, 0.75
AR2FA = str.maketrans({"ي": "ی", "ك": "ک", "ة": "ه", "ؤ": "و", "إ": "أ", "ٱ": "ا"})
DIACR = re.compile(r"[\u064b-\u0652\u0670\u0640]")
TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
FRONT = re.compile(r"\A---\n(.*?)\n---\n", re.S)

RULE_PACKS_FILE = PKG / "rule_packs.json"

_RULING_SECTIONS = ["پاسخ کوتاه", "نکتهٔ ویرایشی", "قاعده یا سازوکار", "در یک نگاه"]
_RULEPACK_SECTIONS = ["نکتهٔ ویرایشی", "پاسخ کوتاه", "قاعده یا سازوکار", "در یک نگاه"]


def tokenize(t: str):
    t = t.translate(AR2FA)
    t = DIACR.sub("", t)
    return [m.group(0) for m in TOKEN.finditer(t) if len(m.group(0)) > 1]


def vault_path() -> Path:
    env = os.environ.get("OP_VAULT_PATH")
    if env:
        return Path(env)
    # repo checkout layout: <root>/vault (this public repo)
    repo_vault = PKG.parents[1] / "vault"
    if repo_vault.is_dir():
        return repo_vault
    return Path(os.path.expanduser("~/workspace/writing-principles/نویسندگی و تولید محتوا"))


def index_path() -> Path:
    env = os.environ.get("OP_INDEX_PATH")
    if env:
        return Path(env)
    # repo checkout layout: <root>/src/obper_mcp -> <root>/index/vault-index.json
    # (keeps the local skill on the live repo index)
    repo = PKG.parents[1] / "index" / "vault-index.json"
    if repo.is_file():
        return repo
    # pip-installed package: use the bundled snapshot
    return PKG / "data" / "vault-index.json"


_idx = None
_idx_loaded_from = None


def load_index():
    global _idx, _idx_loaded_from
    p = index_path()
    if _idx is None or _idx_loaded_from != str(p):
        _idx = json.loads(p.read_text(encoding="utf-8"))
        _idx_loaded_from = str(p)
    return _idx


def _bm25(terms, top_k):
    idx = load_index()
    N, avgdl = idx["N"], idx["avgdl"]
    scored = []
    for d in idx["docs"]:
        s = 0.0
        tf = d["tf"]
        for t in terms:
            f = tf.get(t)
            if not f:
                continue
            idf = idx["idf"].get(t, 0.0)
            denom = f + K1 * (1 - B + B * d["dl"] / avgdl)
            s += idf * f * (K1 + 1) / denom
        if s > 0:
            scored.append((s, d))
    scored.sort(key=lambda x: -x[0])
    return scored[:max(1, top_k)]


def strip_frontmatter(text: str) -> str:
    return FRONT.sub("", text, count=1)


def _status_cache() -> dict:
    return _status_cache.d  # type: ignore
_status_cache.d = {}  # type: ignore


def note_status(note_id: str) -> str:
    """Read `status:` from a note's frontmatter (cached)."""
    cache = _status_cache.d
    if note_id in cache:
        return cache[note_id]
    status = ""
    try:
        text = (vault_path() / note_id).read_text(encoding="utf-8")
        m = FRONT.match(text)
        if m:
            for line in m.group(1).splitlines():
                if line.startswith("status:"):
                    status = line.split(":", 1)[1].strip().strip("'\"")
                    break
    except Exception:
        pass
    cache[note_id] = status
    return status


def extract_section(note_id: str, sections) -> tuple[str, str]:
    """Return (section_name, text) of the first non-empty section found."""
    try:
        text = (vault_path() / note_id).read_text(encoding="utf-8")
    except Exception:
        return "", ""
    body = strip_frontmatter(text)
    for sec in sections:
        m = re.search(rf"^#{{2,3}} {sec}\s*\n(.*?)(?=^#{{2,3}} |\Z)", body, re.M | re.S)
        if m and m.group(1).strip():
            return sec, re.sub(r"\n{3,}", "\n\n", m.group(1).strip())
    return "", ""


def snippet_for(note_id: str, terms, width: int = 320) -> str:
    try:
        text = (vault_path() / note_id).read_text(encoding="utf-8")
    except Exception:
        return ""
    text = strip_frontmatter(text)
    low = text.lower()
    best, best_i = 0, 0
    for t in terms:
        i = low.find(t.lower())
        if i >= 0:
            window = low[max(0, i - width):i + width]
            score = sum(window.count(x.lower()) for x in terms)
            if score > best:
                best, best_i = score, i
    s = max(0, best_i - width // 2)
    frag = text[s:s + width].replace("\n", " ").strip()
    return ("…" if s > 0 else "") + frag + ("…" if s + width < len(text) else "")


# ---------------------------------------------------------------- tools ----

def search_notes(query: str, top_k: int = 5) -> dict:
    terms = tokenize(query)
    if not terms:
        return {"hits": []}
    hits = []
    for s, d in _bm25(terms, min(max(top_k, 1), 10)):
        hits.append({
            "id": d["id"], "title": d["title"], "score": round(s, 3),
            "tags": d["tags"], "type": d["type"], "status": note_status(d["id"]),
            "snippet": snippet_for(d["id"], terms),
        })
    return {"hits": hits}


def read_note_text(note_id: str, max_chars: int = 6000) -> dict:
    p = vault_path() / note_id
    if not p.is_file() or p.suffix != ".md":
        return {"error": "note not found"}
    return {"id": note_id, "text": p.read_text(encoding="utf-8")[:max_chars]}


def map_sections() -> dict:
    vault = vault_path()
    sections = {}
    for p in sorted(vault.rglob("*.md")):
        rel = p.relative_to(vault)
        top = rel.parts[1] if len(rel.parts) > 1 else "(root)"
        sections[top] = sections.get(top, 0) + 1
    return {"sections": sections, "total": sum(sections.values())}


def rebuild_index() -> dict:
    r = subprocess.run(
        [sys.executable, str(PKG / "build_index.py"),
         "--vault", str(vault_path()), "--out", str(index_path())],
        capture_output=True, text=True, timeout=600)
    global _idx, _idx_loaded_from
    _idx, _idx_loaded_from = None, None
    _status_cache.d.clear()
    return {"ok": r.returncode == 0, "log": (r.stdout + r.stderr)[-500:]}


def ruling_for(query: str) -> dict:
    terms = tokenize(query)
    if not terms:
        return {"ruling": None}
    scored = _bm25(terms, 1)
    if not scored:
        return {"ruling": None}
    best, d = scored[0]
    section, text = extract_section(d["id"], _RULING_SECTIONS)
    if not text:
        body = strip_frontmatter((vault_path() / d["id"]).read_text(encoding="utf-8")) \
            if (vault_path() / d["id"]).is_file() else ""
        for para in re.split(r"\n\s*\n", body):
            p = para.strip()
            if len(p) > 60 and not p.startswith(("#", ">", "|")):
                text, section = p, "lead"
                break
    return {"query": query, "title": d["title"], "id": d["id"],
            "section": section, "score": round(best, 3),
            "ruling": text[:1200] or None}


def _shorten(text: str, limit: int = 300) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def load_rule_packs() -> dict:
    return json.loads(RULE_PACKS_FILE.read_text(encoding="utf-8"))


def rule_pack_for(task_type: str, max_rules: int = 10) -> dict:
    """Build the compact «بستهٔ قاعده» checklist for a writing task type.

    Runs each seed query for the task type through BM25, dedupes, keeps only
    status=verified notes, and extracts each note's short editorial ruling.
    """
    packs = load_rule_packs()
    queries = packs.get(task_type)
    custom = False
    if not queries:
        queries, custom = [task_type], True
    seen: dict[str, dict] = {}
    for q in queries:
        terms = tokenize(q)
        if not terms:
            continue
        for s, d in _bm25(terms, 8):
            if d["id"] in seen:
                continue
            if note_status(d["id"]) != "verified":
                continue
            seen[d["id"]] = {"id": d["id"], "title": d["title"], "score": round(s, 3)}
            if len(seen) >= max_rules:
                break
        if len(seen) >= max_rules:
            break
    rules = []
    for doc in list(seen.values())[:max_rules]:
        section, text = extract_section(doc["id"], _RULEPACK_SECTIONS)
        if text:
            rules.append({"title": doc["title"], "rule": _shorten(text), "id": doc["id"]})
    return {"task_type": task_type, "custom_queries": custom,
            "seed_queries": queries, "count": len(rules), "rules": rules}


# Fixed editorial dimensions for the deep-polish pipeline: the task-specific
# checklist plus the five dimensions every Persian text must pass.
DEEP_DIMENSIONS = ["نیم‌فاصله", "ویرگول و نشانه‌گذاری",
                   "ساختار جمله", "انتخاب واژه", "لحن متن"]


def deep_rules_for(task_type: str, per_dim: int = 8) -> dict:
    """Build the full multi-dimensional checklist for deep Persian editing.

    Runs rule_pack_for for the task type plus each fixed editorial dimension,
    dedupes by note id, and returns one merged checklist (~40 rules) plus a
    ready-to-paste ``checklist`` string. This is the knowledge side of the
    general deep-edit loop; any agent (Claude Desktop, Cursor, n8n, ...) runs
    the edit -> review passes itself.
    """
    queries = [task_type, *DEEP_DIMENSIONS]
    seen: dict[str, dict] = {}
    dims = []
    for q in queries:
        before = len(seen)
        pack = rule_pack_for(q, per_dim)
        for r in pack["rules"]:
            if r["id"] not in seen:
                seen[r["id"]] = r
        dims.append({"query": q, "count": len(seen) - before})
    rules = list(seen.values())
    checklist = "\n".join(f"{i + 1}. {r['title']}: {r['rule']}"
                           for i, r in enumerate(rules))
    return {"task_type": task_type, "dimensions": dims,
            "rules_count": len(rules), "count": len(rules),
            "rules": rules, "checklist": checklist}
