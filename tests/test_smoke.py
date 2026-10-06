#!/usr/bin/env python3
"""Smoke tests for obsidian-persian-mcp.

Covers all 9 tools over stdio, the HTTP transport (auth positive/negative),
and the /health endpoint. Run with the search-console venv python:

    ~/workspace/mcp-servers/search-console/.venv/bin/python tests/test_smoke.py

Env:
    OP_SRC  path to the package src dir (default: <repo>/src)
"""
import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = Path(os.environ.get("OP_SRC", REPO / "src"))
BASE_ENV = dict(os.environ, PYTHONPATH=str(SRC), PYTHONUNBUFFERED="1")
PORT = int(os.environ.get("OP_TEST_PORT", "18061"))
API_KEY = "test-secret-123"
PASS, FAIL = "PASS", "FAIL"
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"[{PASS if cond else FAIL}] {name}" + (f" — {detail}" if detail and not cond else ""))


async def stdio_tools():
    from mcp.client.stdio import stdio_client, StdioServerParameters
    from mcp.client.session import ClientSession

    params = StdioServerParameters(
        command=sys.executable,
        args=["-c", "from obper_mcp.server import main; main()"],
        env=BASE_ENV,
    )
    out = {}
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as s:
            await s.initialize()
            tools = (await s.list_tools()).tools
            out["tool_names"] = sorted(t.name for t in tools)

            async def call(name, args):
                res = await s.call_tool(name, args)
                texts = [getattr(c, "text", str(c)) for c in res.content]
                raw = "\n".join(texts)
                try:
                    return json.loads(raw)
                except Exception:
                    # fastmcp>=2 may return structured content directly
                    if res.structuredContent:
                        return res.structuredContent
                    return {"_raw": raw}

            out["search"] = await call("search", {"query": "نیم‌فاصله", "top_k": 3})
            out["read_note"] = await call("read_note", {"note_id": out["search"]["hits"][0]["id"], "max_chars": 500})
            out["map_vault"] = await call("map_vault", {})
            out["ruling"] = await call("ruling", {"query": "فرق نقطه و ویرگول"})
            out["rule_pack"] = await call("rule_pack", {"task_type": "گزارش رسمی", "max_rules": 10})
            out["deep_rules"] = await call("deep_rules", {"task_type": "گزارش رسمی", "per_dim": 8})
            out["smart_rules"] = await call("smart_rules", {
                "text": "در دنیای امروز، این گزارش می‌باشد که توسط تیم تهیه گردیده است, و ارسال می شود.",
                "task_type": "گزارش رسمی", "max_rules": 60})
            out["mechanical_pass"] = await call("mechanical_pass", {
                "text": 'اين متن,دارای "نقل قول" است و می شود خواند؟ 100% تضمینی.'})
    return out


def http_request(method, path, key=None, data=None):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}",
                                 data=json.dumps(data).encode() if data else None,
                                 method=method)
    if data:
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json, text/event-stream")
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read()[:2000], dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:500], dict(e.headers)
    except urllib.error.URLError:
        return 0, b"", {}


def main():
    # ---- stdio: all 9 tools ----
    out = asyncio.run(stdio_tools())
    check("stdio tools listed (9)", out["tool_names"] == sorted(
        ["search", "read_note", "map_vault", "reindex", "ruling", "rule_pack", "deep_rules", "smart_rules", "mechanical_pass"]),
        str(out["tool_names"]))
    check("search returns hits", len(out["search"].get("hits", [])) > 0)
    check("read_note returns text", len(out["read_note"].get("text", "")) > 100)
    check("map_vault total=1577", out["map_vault"].get("total") == 1577,
          str(out["map_vault"].get("total")))
    check("ruling returns a ruling", bool(out["ruling"].get("ruling")))
    rp = out["rule_pack"]
    check("rule_pack returns <=10 rules", 0 < rp.get("count", 0) <= 10, str(rp.get("count")))
    check("rule_pack rules have title+rule",
          all(r.get("title") and r.get("rule") for r in rp.get("rules", [])))
    dr = out["deep_rules"]
    check("deep_rules returns merged checklist",
          dr.get("rules_count", 0) >= 20 and len(dr.get("checklist", "")) > 500,
          str(dr.get("rules_count")))
    check("deep_rules covers 6 dimensions", len(dr.get("dimensions", [])) == 6)
    sr = out["smart_rules"]
    check("smart_rules diagnoses dirty text", len(sr.get("diagnosis", [])) >= 3,
          str([s["signal"] for s in sr.get("diagnosis", [])]))
    check("smart_rules rules carry why",
          all(r.get("why") for r in sr.get("rules", [])) and 0 < sr.get("rules_count", 0) <= 60,
          str(sr.get("rules_count")))
    mp = out["mechanical_pass"]
    check("mechanical_pass fixes deterministically",
          "ي" not in mp["fixed"] and "،" in mp["fixed"] and "«" in mp["fixed"]
          and len(mp.get("fixes", [])) >= 3, mp["fixed"][:80])
    check("mechanical_pass is idempotent", mp.get("clean") is True and mp.get("remaining") == [],
          str(mp.get("remaining")))

    # ---- HTTP transport ----
    proc = subprocess.Popen(
        [sys.executable, "-c", "from obper_mcp.server import main; main()",
         "--transport", "streamable-http", "--host", "127.0.0.1",
         "--port", str(PORT), "--api-key", API_KEY],
        env=BASE_ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            st, _, _ = http_request("GET", "/health")
            if st == 200:
                break
            time.sleep(0.2)
        st, body, _ = http_request("GET", "/health")
        check("GET /health without key -> 200", st == 200, f"status={st}")

        st, _, _ = http_request("POST", "/mcp")
        check("POST /mcp without key -> 401", st == 401, f"status={st}")

        st, _, _ = http_request("POST", "/mcp", key="wrong-key")
        check("POST /mcp with wrong key -> 401", st == 401, f"status={st}")

        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                           "clientInfo": {"name": "smoke", "version": "1"}}}
        st, body, headers = http_request("POST", "/mcp", key=API_KEY, data=init)
        check("POST /mcp initialize with key -> not 401", st != 401, f"status={st}")
        check("initialize returns session", st == 200 and b"result" in body, f"status={st}")
    finally:
        proc.terminate()
        proc.wait(timeout=10)

    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
