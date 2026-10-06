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


# ---------------------------------------------------------------------------
# Smart (diagnosis-driven) rule selection.
# Instead of a fixed checklist, the text is first scanned for editorial risk
# signals; rules are then pulled for the issues actually present, each tagged
# with *why* it was selected.

SIGNAL_QUERIES = {
    "long_sentence": ["جمله طولانی", "ویرایش جمله"],
    "bureaucratic": ["حشو اداری", "نثر اداری"],
    "passive": ["جمله مجهول"],
    "passive_freq": ["جمله مجهول", "تنوع فعل"],
    "arabic_chars": ["حروف عربی", "رسم‌الخط فارسی"],
    "latin_punct": ["نشانه‌گذاری فارسی"],
    "zwnj": ["نیم‌فاصله"],
    "quotes": ["نقل‌قول مستقیم", "گیومه"],
    "numbers": ["نگارش اعداد فارسی"],
    "percent": ["درصد"],
    "english": ["وام‌واژه", "معادل‌سازی"],
    "cliche": ["کلیشه", "شروع متن"],
    "repetition": ["تکرار واژه"],
    "long_para": ["پاراگراف", "بندبندی"],
    "no_para": ["پاراگراف", "بندبندی"],
    "questions": ["علامت سؤال"],
}


def diagnose(text: str) -> list:
    """Scan Persian text for editorial risk signals (stdlib regex only).

    Returns a list of {"signal", "weight", "evidence", "queries"} dicts.
    Weights: 3 = critical, 2 = notable, 1 = minor.
    """
    t = text or ""
    out = []

    def add(sid, weight, evidence):
        out.append({"signal": sid, "weight": weight, "evidence": evidence,
                    "queries": SIGNAL_QUERIES.get(sid, [])})

    sents = [s.strip() for s in re.split(r"[.!?…؟\n]+", t) if s.strip()]
    long_s = [s for s in sents if len(s.split()) > 35]
    if long_s:
        add("long_sentence", 3, f"{len(long_s)} جملهٔ بالای ۳۵ واژه")

    fossils = ["می‌باشد", "می‌باشند", "گردید", "لذا", "جهت", "کلیه",
               "نظر به", "بدینوسیله", "بدین‌وسیله", "فوق‌الذکر", "مذکور"]
    found = [w for w in fossils if w in t]
    if found:
        add("bureaucratic", 3, "حشو اداری: " + "، ".join(found[:3]))

    if re.search(r"(توسط|از سوی|به‌وسیلهٔ|به وسیلهٔ)", t):
        add("passive", 2, "عامل مجهول‌ساز (توسط/از سوی)")
    if len(re.findall(r"(شده است|گردیده است|می‌شود|می‌شوند|خواهد شد)", t)) >= 2:
        add("passive_freq", 2, "تکرار صورت‌های مجهول")

    if re.search(r"[يك]", t):
        add("arabic_chars", 3, "حروف عربی «ي» یا «ك» در متن")
    if re.search(r"[,;!?\"'()\[\]–—-]", t):
        add("latin_punct", 3, "نشانه‌گذاری لاتین در متن")
    zwnj_hits = []
    if re.search(r"(^|\s)(می|نمی)\s+\S", t):
        zwnj_hits.append("«می/نمی» جدا از فعل")
    if re.search(r"\s(ها|های|تر|ترین|گری)\s", t):
        zwnj_hits.append("پسوند جدا («ها/تر/ترین»)")
    if zwnj_hits:
        add("zwnj", 3, "؛ ".join(zwnj_hits))

    if '"' in t or "«" in t:
        add("quotes", 2, "نقل‌قول در متن")
    if re.search(r"[0-9۰-۹]", t):
        add("numbers", 2, "عدد در متن")
    if "%" in t or "٪" in t or "درصد" in t:
        add("percent", 2, "درصد در متن")
    if re.search(r"[a-zA-Z]", t):
        add("english", 2, "واژهٔ لاتین در متن")

    cliches = ["در دنیای امروز", "شایان ذکر است", "لازم به ذکر است",
               "در این راستا", "گفتنی است"]
    fc = [c for c in cliches if c in t]
    if fc:
        add("cliche", 3, "کلیشه: " + "، ".join(fc[:2]))

    rep = 0
    for s in sents:
        cnt: dict[str, int] = {}
        for w in s.split():
            if len(w) > 2:
                cnt[w] = cnt.get(w, 0) + 1
        if any(v >= 4 for v in cnt.values()):
            rep += 1
    if rep:
        add("repetition", 2, f"تکرار واژه در {rep} جمله")

    paras = [p for p in t.split("\n") if p.strip()]
    if paras and max(len(p.split()) for p in paras) > 120:
        add("long_para", 2, "بندِ خیلی بلند (بالای ۱۲۰ واژه)")
    if len(paras) <= 1 and len(t.split()) > 200:
        add("no_para", 2, "متن تک‌بندِ بلند")
    if "؟" in t:
        add("questions", 1, "جملهٔ پرسشی در متن")
    return out


def smart_rules_for(text: str, task_type: str, max_rules: int = 60,
                    per_query: int = 6) -> dict:
    """Diagnose the text, then build a tailored deep-edit checklist.

    Layer 1 (base): the task-type rule_pack (up to 10 rules).
    Layer 2 (diagnosis-driven): for each detected risk signal, run its
    targeted queries and add the best verified notes, ordered by signal
    weight. Every rule carries ``why`` — the evidence that selected it.
    """
    diag = diagnose(text)
    seen: dict[str, dict] = {}
    base = rule_pack_for(task_type, 10)
    for r in base["rules"]:
        if r["id"] not in seen:
            seen[r["id"]] = {**r, "why": f"چک‌لیست پایهٔ «{task_type}»"}
    for sig in sorted(diag, key=lambda s: -s["weight"]):
        for q in sig["queries"]:
            pack = rule_pack_for(q, per_query)
            for r in pack["rules"]:
                if r["id"] not in seen:
                    if len(seen) >= max_rules:
                        break
                    seen[r["id"]] = {**r, "why": sig["evidence"]}
            if len(seen) >= max_rules:
                break
        if len(seen) >= max_rules:
            break
    rules = list(seen.values())
    checklist = "\n".join(
        f"{i + 1}. {r['title']}: {r['rule']} (چرا: {r['why']})"
        for i, r in enumerate(rules))
    return {"task_type": task_type, "diagnosis": diag,
            "rules_count": len(rules), "count": len(rules),
            "rules": rules, "checklist": checklist}


# ---------------------------------------------------------------------------
# Deterministic mechanical layer: fixes what needs no judgment, and proves it.
# Unlike the LLM passes (which can "not notice"), this scans everything.

def mechanical_fix(text: str) -> dict:
    """Fix mechanically-safe Persian issues; report what remains.

    100% deterministic: same input -> same output. Covers the error classes
    that need no judgment (Arabic chars, Latin punctuation, ZWNJ on می/نمی,
    spacing). Anything ambiguous (e.g. em/en dashes) is *flagged*, not guessed.
    Returns {"fixed", "fixes", "remaining", "clean"}.
    """
    t = text or ""
    fixes: list = []

    def sub(pattern, repl, name):
        nonlocal t
        nt, n = re.subn(pattern, repl, t)
        if n:
            fixes.append({"rule": name, "count": n})
            t = nt

    sub(r"ي", "ی", "ي→ی")
    sub(r"ك", "ک", "ك→ک")
    sub(r"ة", "ه", "ة→ه")
    sub(r"ؤ", "و", "ؤ→و")
    sub(r",", "،", ",→،")
    sub(r";", "؛", ";→؛")
    sub(r"\?", "؟", "?→؟")
    sub(r"%", "٪", "%→٪")
    # straight quotes -> « » (paired)
    if '"' in t:
        parts = t.split('"')
        t = "".join(p + ("«" if i % 2 == 0 else "»")
                    for i, p in enumerate(parts[:-1])) + parts[-1]
        fixes.append({"rule": '"→«»', "count": t.count("«")})
    sub(r"(^|\s)می\s+(?=\S)", r"\1می‌", "می‌")
    sub(r"(^|\s)نمی\s+(?=\S)", r"\1نمی‌", "نمی‌")
    sub(r"\s+([،؛؟٪»])", r"\1", "حذف فاصلهٔ پیش از نشانه")
    sub(r"([،؛؟])(?=[^\s،؛؟»])", r"\1 ", "فاصلهٔ پس از نشانه")
    sub(r"([«])\s+", r"\1", "حذف فاصلهٔ پس از «")
    sub(r" {2,}", " ", "فاصلهٔ چندتایی")
    sub(r"[ \t]+\n", "\n", "فاصلهٔ پایان سطر")
    sub(r"\n{3,}", "\n\n", "سطر خالی اضافه")
    t = t.strip()

    remaining = []
    if re.search(r"[يك]", t):
        remaining.append("حروف عربی باقی‌مانده")
    if re.search(r"[,;?]", t):
        remaining.append("نشانهٔ لاتین باقی‌مانده")
    if re.search(r"[–—]", t):
        remaining.append("خط تیرهٔ فرنگی (نیاز به تصمیم انسانی)")
    if re.search(r"(^|\s)(می|نمی)\s+\S", t):
        remaining.append("«می/نمی» جدا از فعل")
    return {"fixed": t, "fixes": fixes,
            "remaining": remaining, "clean": not remaining}
