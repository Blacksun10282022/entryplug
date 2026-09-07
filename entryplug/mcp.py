# What: `plug mcp` — an MCP server over stdio with exactly one tool, `search` (the same function as plug search).
#       JSON-RPC is hand-written; the mcp package is not a dependency (D01).
# In:   one JSON-RPC message per line on stdin: initialize · notifications/initialized · ping · tools/list · tools/call.
# Out:  one response per line on stdout (UTF-8); notifications get no reply; unknown method → -32601;
#       bad JSON → -32700; an error inside the tool → -32603.
# Not:  zero write surface — this process physically cannot write content (read-only sqlite connection);
#       injects nothing into the pilot; no resources, no prompts.
# Who:  the pilot's MCP client (pilots/claude-code/.mcp.json · Codex's mcp config) · contact (first contact, step 2) · tests.
# Note: protocolVersion echoes the client's (default 2025-06-18); capabilities declare tools only.
#       Tool input: query (string or list) · scope (tools default / corpus / all) · tool · kind · k (8 → 60) · per_doc (2 → 5).
#       Tool output: content[0].text = compact index lines + the tail "showing k/N". Paragraphs are fetched by the
#       pilot's own Read using file#Lstart-Lend.
#       serve(cfg, inp, out) accepts injected streams so tests need no subprocess; cli passes sys.stdin/stdout buffers.
# Deps: stdlib json · search.
import json, sys
from . import __version__, search

TOOL = {
    "name": "search",
    "description": "Read-only retrieval. Default scope is the equipment layer (dict · playbooks · records); "
                   "scope=corpus searches the corpus. Takes one query or several (different angles are merged "
                   "round-robin, never reranked) and returns compact index lines: id · source · file#Lstart-Lend "
                   "[pos] · kind · excerpt (<=120 chars), with a tail line 'showing k/N'. Fetch paragraphs yourself "
                   "with Read using the line numbers.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {"anyOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
                      "description": "one query, or several queries taking different angles"},
            "scope": {"type": "string", "enum": ["tools", "corpus", "all"], "default": "tools"},
            "tool": {"type": "string", "description": "restrict to one piece of equipment"},
            "kind": {"type": "string", "description": "concept / method / playbook / record / material / corpus"},
            "k": {"type": "integer", "default": 8, "minimum": 1, "maximum": 60},
            "per_doc": {"type": "integer", "default": 2, "minimum": 1, "maximum": 5},
        },
        "required": ["query"],
    },
}


def handle(cfg, msg):
    """One request → (result, error). A notification returns (None, None)."""
    m, p = msg.get("method", ""), msg.get("params") or {}
    if m == "initialize":
        return {"protocolVersion": p.get("protocolVersion", "2025-06-18"), "capabilities": {"tools": {}},
                "serverInfo": {"name": "entryplug", "version": __version__}}, None
    if m.startswith("notifications/"):
        return None, None
    if m == "ping":
        return {}, None
    if m == "tools/list":
        return {"tools": [TOOL]}, None
    if m == "tools/call":
        a = p.get("arguments") or {}
        if p.get("name") != "search":
            return None, {"code": -32602, "message": "there is only one tool: search"}
        if not a.get("query"):
            return {"content": [{"type": "text", "text": "query must not be empty"}], "isError": True}, None
        try:
            res = search.search(cfg, a["query"], scope=a.get("scope", "tools"), tool=a.get("tool"), kind=a.get("kind"),
                                k=a.get("k", 8), per_doc=a.get("per_doc", 2), auto_index=False)
        except FileNotFoundError as e:           # no index: report as a tool error, not a protocol error
            return {"content": [{"type": "text", "text": str(e)}], "isError": True}, None
        return {"content": [{"type": "text", "text": search.format_rows(res)}], "isError": False}, None
    return None, {"code": -32601, "message": "no such method: %s" % m}


def serve(cfg, inp=None, out=None):
    inp, out = inp or sys.stdin.buffer, out or sys.stdout.buffer
    def send(obj):
        out.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
        out.flush()
    for raw in iter(inp.readline, b""):
        raw = raw.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw)
        except ValueError:
            send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "not JSON"}})
            continue
        try:
            result, error = handle(cfg, msg)
        except Exception as e:                       # an error inside the tool must reach the client, not kill the process
            result, error = None, {"code": -32603, "message": "%s: %s" % (type(e).__name__, e)}
        if msg.get("id") is None:
            continue
        send({"jsonrpc": "2.0", "id": msg["id"], "error": error} if error else {"jsonrpc": "2.0", "id": msg["id"], "result": result})
    return 0
