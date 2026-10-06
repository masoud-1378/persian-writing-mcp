#!/usr/bin/env python3
"""Build BM25 index over Masoud's Obsidian Persian-writing vault.

Usage: build_index.py [--vault DIR] [--out index/vault-index.json]
"""
import argparse, json, math, os, re, sys
from pathlib import Path

# ---- Persian text normalization ----
AR2FA = str.maketrans({"ي": "ی", "ك": "ک", "ة": "ه", "ؤ": "و", "إ": "ا", "أ": "ا", "ٱ": "ا"})
DIACR = re.compile(r"[\u064b-\u0652\u0670\u0640]")  # tanvin/harakat/tatweel
TOKEN = re.compile(r"[^\W_]+", re.UNICODE)  # letters+digits, keeps ZWNJ-joined words

def normalize(t: str) -> str:
    t = t.translate(AR2FA)
    t = DIACR.sub("", t)
    return t

def tokenize(t: str):
    t = normalize(t)
    return [m.group(0) for m in TOKEN.finditer(t) if len(m.group(0)) > 1]

FRONT = re.compile(r"\A---\n(.*?)\n---\n", re.S)
WIKILINK = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")
HEADING = re.compile(r"^#{1,3}\s+(.+)$", re.M)

def parse_note(path: Path):
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None
    fm = {}
    body = text
    m = FRONT.match(text)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line and not line.startswith(" ") and not line.startswith("\t"):
                k, v = line.split(":", 1)
                fm[k.strip()] = v.strip()
        body = text[m.end():]
    title = fm.get("title") or ""
    if not title:
        h = HEADING.search(body)
        title = h.group(1).strip() if h else path.stem
    # strip markdown noise for indexing but keep words
    clean = re.sub(r"[#>*`\-_|]", " ", body)
    clean = WIKILINK.sub(r" \1 ", clean)
    return {
        "title": title,
        "aliases": fm.get("aliases", ""),
        "tags": fm.get("tags", ""),
        "type": fm.get("type", ""),
        "headings": HEADING.findall(body)[:12],
        "links": sorted(set(WIKILINK.findall(body)))[:40],
        "text": clean,
    }

def build(vault: Path):
    docs = []
    for p in sorted(vault.rglob("*.md")):
        d = parse_note(p)
        if not d:
            continue
        rel = str(p.relative_to(vault))
        title_toks = tokenize(d["title"] + " " + d["aliases"] + " " + " ".join(d["headings"]))
        body_toks = tokenize(d["text"])
        docs.append({
            "id": rel,
            "title": d["title"],
            "tags": d["tags"],
            "type": d["type"],
            "headings": d["headings"],
            "links": d["links"],
            "title_toks": title_toks,
            "body_toks": body_toks,
        })
    # document frequencies over combined tokens
    N = len(docs)
    df = {}
    doc_lens = []
    for d in docs:
        seen = set(d["title_toks"]) | set(d["body_toks"])
        for t in seen:
            df[t] = df.get(t, 0) + 1
        doc_lens.append(len(d["title_toks"]) * 3 + len(d["body_toks"]))
    avgdl = sum(doc_lens) / max(N, 1)
    idf = {t: math.log(1 + (N - df_t + 0.5) / (df_t + 0.5)) for t, df_t in df.items()}
    # term frequencies per doc (title weighted x3)
    index = []
    for d, dl in zip(docs, doc_lens):
        tf = {}
        for t in d["title_toks"]:
            tf[t] = tf.get(t, 0) + 3
        for t in d["body_toks"]:
            tf[t] = tf.get(t, 0) + 1
        index.append({
            "id": d["id"], "title": d["title"], "tags": d["tags"],
            "type": d["type"], "headings": d["headings"], "links": d["links"],
            "dl": dl, "tf": tf,
        })
    return {"N": N, "avgdl": avgdl, "idf": idf, "docs": index}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", default=os.path.expanduser("~/workspace/writing-principles/نویسندگی و تولید محتوا"))
    ap.add_argument("--out", default=os.environ.get("OP_INDEX_PATH") or os.path.join(os.path.dirname(__file__), "..", "..", "index", "vault-index.json"))
    a = ap.parse_args()
    idx = build(Path(a.vault))
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(idx, ensure_ascii=False), encoding="utf-8")
    print(f"indexed {idx['N']} notes -> {out} ({out.stat().st_size/1e6:.1f} MB)")

if __name__ == "__main__":
    main()
