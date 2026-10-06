#!/usr/bin/env python3
"""Obsidian Persian-writing vault — MCP server.

Tools: search | read_note | map_vault | reindex | ruling | rule_pack

Transports:
    obper-mcp                                     # stdio (default; Claude Desktop, Cursor, ...)
    obper-mcp --transport streamable-http --port 8060 --api-key SECRET
    obper-mcp --transport sse --port 8060 --api-key SECRET

HTTP transports require an API key (--api-key or OP_MCP_API_KEY), unless you
pass --no-auth (only allowed when bound to localhost). Clients authenticate
with `Authorization: Bearer SECRET` or `?api_key=SECRET`.
The vault location is configurable with OP_VAULT_PATH.
"""
import argparse
import os
import re
import sys
from pathlib import Path

# FastMCP's vendored httpx crashes on bracketed IPv6 literals (e.g. [::1])
# in no_proxy. Normalize before it reads the environment.
for _k in ("no_proxy", "NO_PROXY"):
    _v = os.environ.get(_k)
    if _v and "[" in _v:
        os.environ[_k] = re.sub(r"\[([0-9A-Fa-f:]+)\]", r"\1", _v)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastmcp import FastMCP  # noqa: E402
from starlette.middleware import Middleware  # noqa: E402
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402
from starlette.responses import JSONResponse  # noqa: E402
from starlette.routing import Route  # noqa: E402

from obper_mcp import core  # noqa: E402

mcp = FastMCP("obsidian-persian")


@mcp.tool()
def search(query: str, top_k: int = 5) -> dict:
    """Search Masoud's Persian writing/editing vault. Returns ranked notes with snippets."""
    return core.search_notes(query, top_k)


@mcp.tool()
def read_note(note_id: str, max_chars: int = 6000) -> dict:
    """Read a full note from the vault by its id (as returned by search)."""
    return core.read_note_text(note_id, max_chars)


@mcp.tool()
def map_vault() -> dict:
    """The vault's section tree (numbered sections) with note counts."""
    return core.map_sections()


@mcp.tool()
def reindex() -> dict:
    """Rebuild the search index (run after notes are added/edited)."""
    return core.rebuild_index()


@mcp.tool()
def ruling(query: str) -> dict:
    """Get the vault's short editorial ruling for a question/doubt.

    Searches the vault, takes the best note, and returns its short ruling
    (پاسخ کوتاه / نکتهٔ ویرایشی / قاعده یا سازوکار) with the note id.
    Use this as the virtual editor's verdict before finalizing Persian text.
    """
    return core.ruling_for(query)


@mcp.tool()
def rule_pack(task_type: str, max_rules: int = 10) -> dict:
    """Build the compact «بستهٔ قاعده» checklist for a Persian writing task.

    task_type is one of: گزارش رسمی، ایمیل اداری، لندینگ، مقاله، کپشن،
    نامهٔ اداری، پروپوزال، خبر، مصاحبه، متن وب، پست شبکهٔ اجتماعی، جواب چت.
    (Any other value is used as a free-form search query.)
    Runs seed queries through the vault, keeps only status=verified notes,
    and returns up to max_rules items as «عنوان: حکم کوتاه».
    This is step 2-3 of the «حالت کامل» pipeline in the Persian OS.
    """
    return core.rule_pack_for(task_type, max_rules)


class _ApiKeyMiddleware(BaseHTTPMiddleware):
    """Bearer / ?api_key gate for the HTTP transports. /health stays open."""

    def __init__(self, app, api_key: str):
        super().__init__(app)
        self.api_key = api_key

    async def dispatch(self, request, call_next):
        if request.url.path == "/health":
            return await call_next(request)
        authz = request.headers.get("authorization", "")
        key = request.query_params.get("api_key", "")
        if authz == f"Bearer {self.api_key}" or (key and key == self.api_key):
            return await call_next(request)
        return JSONResponse({"error": "unauthorized"}, status_code=401)


async def _health(request):
    return JSONResponse({"ok": True, "service": "obsidian-persian-mcp"})


def main() -> None:
    ap = argparse.ArgumentParser(prog="obper-mcp", description="Persian writing vault MCP server.")
    ap.add_argument("--transport", default=os.environ.get("OP_MCP_TRANSPORT", "stdio"),
                    choices=["stdio", "streamable-http", "sse"])
    ap.add_argument("--host", default=os.environ.get("OP_MCP_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("OP_MCP_PORT", "8060")))
    ap.add_argument("--path", default=os.environ.get("OP_MCP_PATH", "/mcp"),
                    help="HTTP mount path for the MCP endpoint (default /mcp).")
    ap.add_argument("--api-key", default=os.environ.get("OP_MCP_API_KEY"),
                    help="Required for HTTP transports (or OP_MCP_API_KEY).")
    ap.add_argument("--no-auth", action="store_true",
                    help="Allow unauthenticated HTTP. Only permitted on localhost.")
    args = ap.parse_args()

    if args.transport == "stdio":
        mcp.run()
        return

    if not args.api_key and not args.no_auth:
        ap.error("HTTP transports need --api-key (or OP_MCP_API_KEY); "
                 "or pass --no-auth to allow open access on localhost.")
    if args.no_auth and args.host not in ("127.0.0.1", "localhost", "::1"):
        ap.error("--no-auth is only allowed when bound to localhost.")

    middleware = [Middleware(_ApiKeyMiddleware, api_key=args.api_key)] if args.api_key else []
    app = mcp.http_app(path=args.path, transport=args.transport, middleware=middleware)
    app.routes.append(Route("/health", _health))

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
