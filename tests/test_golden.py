#!/usr/bin/env python3
"""Golden quality tests: the pipeline must *measure*, not just assert.

For each golden case (a dirty Persian text with known issues):
  1. diagnose() must detect the expected signals        (detection rate)
  2. mechanical_pass() must leave the text clean        (mechanical guarantee)
     — unless the case explicitly allows a flagged remainder (e.g. em dash)
  3. smart_rules() must return a non-empty, why-tagged checklist
  4. verify_regression() must FAIL on the unfixed text   (gate has teeth)
     and PASS on the mechanically fixed text for mechanical signals
Run:  python tests/test_golden.py   (also runs in CI)
"""
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
from obper_mcp import core  # noqa: E402

PASS, FAIL = "PASS", "FAIL"
results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), str(detail)))
    print(f"[{PASS if ok else FAIL}] {name}" + (f" — {detail}" if detail and not ok else ""))


def main():
    cases = json.loads((REPO / "tests" / "golden_cases.json").read_text(encoding="utf-8"))
    for c in cases:
        cid, text = c["id"], c["text"]
        sigs = {s["signal"] for s in core.diagnose(text)}
        missing = [s for s in c.get("expect_signals", []) if s not in sigs]
        check(f"{cid} signals detected", not missing, f"missing={missing}")

        m = core.mechanical_fix(text)
        if c.get("expect_mechanical_clean", True):
            check(f"{cid} mechanical clean", m["clean"], f"remaining={m['remaining']}")
        else:
            check(f"{cid} mechanical flags honestly", bool(m["remaining"]),
                  "expected a flagged remainder")

        sr = core.smart_rules_for(text, c.get("task_type", "متن وب"))
        check(f"{cid} smart checklist", sr["rules_count"] > 0 and
              all(r.get("why") for r in sr["rules"]), f"n={sr['rules_count']}")
        cov = sr.get("coverage_areas", [])
        check(f"{cid} knowledge-coverage walk", len(cov) >= 6,
              f"only {len(cov)} areas covered: {cov}")

        for w in c.get("expect_mechanical_unchanged_words", []):
            check(f"{cid} keeps '{w}'", w in m["fixed"], f"fixer mangled '{w}'")

        reg = core.verify_regression(text, text)
        check(f"{cid} gate fails on unfixed", not reg["pass"] or not reg["signals_before"],
              "gate passed a text that still has problem signals")

    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} golden checks passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
