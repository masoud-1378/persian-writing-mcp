# Using obsidian-persian-mcp with n8n

Two ways to connect n8n to this server. **HTTP is recommended** — it works
whether n8n runs on the same machine, in Docker, or in n8n Cloud.

## 1. Start the server (HTTP)

```bash
export OP_MCP_API_KEY='a-long-random-secret'
obper-mcp --transport streamable-http --host 0.0.0.0 --port 8060
```

Or with Docker (build from the workspace root; the vault is bundled in):

```bash
docker build -f mcp-servers/obsidian-persian/Dockerfile -t obsidian-persian-mcp ~/workspace
docker run -p 8060:8060 -e OP_MCP_API_KEY='a-long-random-secret' obsidian-persian-mcp
```

To point at a different vault copy: `-e OP_VAULT_PATH=/data/vault -v /path/to/vault:/data/vault`
(then run the `reindex` tool once, or mount a matching index via `OP_INDEX_PATH`).

`GET /health` answers without a key (for load balancers). Everything under
`/mcp` needs `Authorization: Bearer <key>` or `?api_key=<key>`.

## 2a. Native node: MCP Client Tool (for an AI editor agent)

n8n ships an **MCP Client Tool** node (AI / Agents category) that consumes an
external MCP server as tools for an AI Agent:

1. Add **MCP Client Tool** as a tool sub-node of an **AI Agent**.
2. Endpoint: `http://<host>:8060/mcp` (use `/sse` if you started the server
   with `--transport sse`).
3. Authentication: Bearer → your `OP_MCP_API_KEY`.
4. Tools: **Selected** — `rule_pack` (the checklist builder), plus `search`,
   `ruling` and `read_note` if you want the agent to consult the vault live.

Prompt the agent as a Persian editor: first call `rule_pack` with the text's
`task_type` (گزارش رسمی، ایمیل اداری، لندینگ، مقاله، کپشن، نامهٔ اداری،
پروپوزال، خبر، مصاحبه، متن وب، پست شبکهٔ اجتماعی، جواب چت), apply every rule
in the returned checklist to the input text, then return the edited text.

## 2b. Community node: deterministic workflow (no AI needed for the checklist)

Install `n8n-nodes-mcp` via **Settings → Community nodes**, then use the
**MCP Client** node with an **Execute Tool** operation:

- **Connection type**: `http` (or `sse`)
- **URI Override**: `http://<host>:8060/mcp`
- **Headers Override**: `{"Authorization": "Bearer <your key>"}`
- **Operation**: Execute Tool → **Tool**: `rule_pack`
- **Tool parameters** (JSON):

```json
{
  "task_type": "گزارش رسمی",
  "max_rules": 10
}
```

`rule_pack` only draws from notes with `status=verified` and returns up to 10
«عنوان: حکم کوتاه» rules. Feed its output plus the input text into your editor
agent (or any LLM node) with the instruction to apply every rule.

An importable example — webhook receives Persian text → `rule_pack` →
AI editor agent → edited text — lives in
[`examples/n8n-fa-editor.json`](../examples/n8n-fa-editor.json).
Import it via **Workflows → ⋯ → Import from file**, then set your API key
and connect an LLM.

## 2c. STDIO (same machine only)

If n8n runs on the same host as the server, the community node also supports
`cmd` (STDIO) mode: **Command** = `obper-mcp`, no HTTP needed. Point the vault
with `OP_VAULT_PATH` in the n8n process environment.

## Security notes

- Never expose the HTTP endpoint to the internet without `OP_MCP_API_KEY`.
  For public exposure, put it behind TLS (reverse proxy) and keep the key long
  and random.
- The server is **read-only by design**, except `reindex` (rebuilds the local
  search index). It never writes to your notes.
