#!/usr/bin/env python3
"""Build the fine-tuning dataset: clean Persian text + engineered corruptions.

The pipeline's future training data comes from three tiers:
  1. synthetic (this tool): clean text x controlled corruptions -> (dirty, clean, labels)
  2. organic: logged pipeline runs that passed all gates -> (dirty, clean, rules)
  3. human-gold: runs approved by the human reviewer -> highest weight

Usage:
  python tools/build_dataset.py --input /tmp/clean_paras.json --output dataset/seed.jsonl --n 500

Each output line: {"dirty","clean","corruptions","source","task_type"}.
Corruptions are exactly the error families the pipeline is built to fix,
so every pair is learnable (no impossible targets).
"""
import argparse
import json
import random
import re
import sys

CORRUPTIONS = {}


def corruption(name):
    def deco(fn):
        CORRUPTIONS[name] = fn
        return fn
    return deco


@corruption("arabic_chars")
def c_arabic(t, rng):
    def sub(m):
        return m.group(0) if rng.random() > 0.5 else {"ی": "ي", "ک": "ك"}[m.group(0)]
    return re.sub(r"[یک]", sub, t)


@corruption("zwnj_drop")
def c_zwnj(t, rng):
    # می‌شود -> می شود  (ZWNJ to space)
    return t.replace("\u200c", " ")


@corruption("latin_punct")
def c_latin_punct(t, rng):
    return (t.replace("،", ",").replace("؟", "?").replace("؛", ";")
             .replace("«", '"').replace("»", '"'))


@corruption("bureaucratize")
def c_bureaucratic(t, rng):
    swaps = [(r"\bاست\b", "می‌باشد"), (r"\bشد\b", "گردید"),
             (r"\bبرای\b", "جهت"), (r"\bهمه\b", "کلیه"),
             (r"\bاما\b", "لیکن")]
    for pat, rep in swaps:
        if rng.random() < 0.6:
            t = re.sub(pat, rep, t)
    return t


@corruption("sentence_merge")
def c_merge(t, rng):
    sents = [s.strip() for s in re.split(r"(?<=[.؟])\s+", t) if s.strip()]
    if len(sents) < 3:
        return t
    i = rng.randrange(len(sents) - 1)
    sents[i] = sents[i].rstrip(".؟") + "، " + sents[i + 1][0].lower() + sents[i + 1][1:]
    del sents[i + 1]
    return " ".join(sents)


@corruption("para_flatten")
def c_flatten(t, rng):
    return re.sub(r"\n+", " ", t)


@corruption("cliche_prefix")
def c_cliche(t, rng):
    cliches = ["در دنیای امروز، ", "شایان ذکر است که ", "لازم به ذکر است که "]
    return rng.choice(cliches) + t


def dirty_text(clean, rng, n_corr=3):
    names = rng.sample(sorted(CORRUPTIONS), k=min(n_corr, len(CORRUPTIONS)))
    t, applied = clean, []
    for n in names:
        new_t = CORRUPTIONS[n](t, rng)
        if new_t != t:  # only label corruptions that actually changed something
            applied.append(n)
        t = new_t
    return t, applied


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    items = json.load(open(args.input, encoding="utf-8"))
    rng = random.Random(args.seed)
    out = []
    for it in items:
        clean = re.sub(r"\s+", " ", it["text"]).strip()
        if len(clean) < 200:
            continue
        for _ in range(2):  # two dirty variants per clean text
            dirty, names = dirty_text(clean, rng, n_corr=rng.randint(1, 4))
            if dirty == clean:
                continue
            out.append({"dirty": dirty, "clean": clean,
                        "corruptions": names, "source": it.get("source", "?"),
                        "task_type": "متن عمومی"})
            if len(out) >= args.n:
                break
        if len(out) >= args.n:
            break

    with open(args.output, "w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"wrote {len(out)} pairs -> {args.output}")


if __name__ == "__main__":
    main()
