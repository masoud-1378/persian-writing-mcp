# persian-writing-mcp

[![tests](https://github.com/masoud-1378/persian-writing-mcp/actions/workflows/test.yml/badge.svg)](https://github.com/masoud-1378/persian-writing-mcp/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> والت ۱۵۷۷ یادداشتی نویسندگی و ویراستاری فارسی، به‌صورت یک سرور MCP:
> جست‌وجو، حکم ویراستاری و «بستهٔ قاعده» برای هر نوع متن — از n8n تا هر کلاینت MCP.

Masoud's Persian writing/editing vault (1577 Obsidian notes: orthography,
punctuation, word choice, sentence & paragraph, style, editing process,
checklists) as an MCP server. stdio for local AI clients, Streamable HTTP
for n8n and teams.

Six tools:

| tool | what it does |
|---|---|
| `search` | BM25 search over the vault (Persian-aware); ranked notes with snippets |
| `read_note` | read a full note by id |
| `map_vault` | section tree with note counts |
| `reindex` | rebuild the search index after notes change |
| `ruling` | the vault's short editorial verdict for a question (نکتهٔ ویرایشی / پاسخ کوتاه) |
| `rule_pack` | the compact «بستهٔ قاعده» checklist for a task type: runs seed queries, keeps only `status=verified` notes, returns up to 10 «عنوان: حکم کوتاه» rules |

## Install

```bash
python3 -m venv .venv && .venv/bin/pip install -e .
```

Or Docker (build from the repo root):

```bash
docker build -t persian-writing-mcp .
docker run -p 8060:8060 -e OP_MCP_API_KEY='a-long-random-secret' persian-writing-mcp
```

Requires Python 3.10+.

## Run

```bash
obper-mcp                                            # stdio (default)
obper-mcp --transport streamable-http --port 8060 --api-key SECRET
obper-mcp --transport sse --port 8060 --api-key SECRET
```

## Environment

| variable | default | meaning |
|---|---|---|
| `OP_MCP_TRANSPORT` | `stdio` | `stdio`, `streamable-http`, `sse` |
| `OP_MCP_HOST` | `127.0.0.1` | bind host for HTTP |
| `OP_MCP_PORT` | `8060` | bind port for HTTP |
| `OP_MCP_PATH` | `/mcp` | HTTP mount path for the MCP endpoint |
| `OP_MCP_API_KEY` | — | required for HTTP (or `--api-key`); `/health` stays open |
| `OP_VAULT_PATH` | `./vault` in a repo checkout | vault directory |
| `OP_INDEX_PATH` | bundled `data/vault-index.json`, else `index/vault-index.json` | search index file |

HTTP clients authenticate with `Authorization: Bearer <key>` or `?api_key=<key>`.
`GET /health` answers without a key (for load balancers).

## rule_pack task types

گزارش رسمی، ایمیل اداری، لندینگ، مقاله، کپشن، نامهٔ اداری، پروپوزال،
خبر، مصاحبه، متن وب، پست شبکهٔ اجتماعی، جواب چت.
Seed queries per type live in `src/obper_mcp/rule_packs.json` — edit them to
retune the checklist. Any other `task_type` value is used as a free-form query.

## Reindex

After adding or editing notes, rebuild the index:

```bash
obper-mcp  # via the reindex tool, or directly:
python -m obper_mcp.build_index --vault <dir> --out <index.json>
```

The index snapshots inside the package (`src/obper_mcp/data/vault-index.json`)
so installs work out of the box; refresh it after vault changes that matter.

## n8n

See [docs/n8n.md](docs/n8n.md) and the importable example
[examples/n8n-fa-editor.json](examples/n8n-fa-editor.json)
(webhook → `rule_pack` → AI editor agent → edited Persian text).
