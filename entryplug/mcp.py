# 做什么：`plug mcp`——stdio 上的 MCP 服务，只有一个工具 `search`（与 plug search 同一函数）。手写 JSON-RPC，不依赖 mcp 包（D01）。
# 输入：stdin 每行一个 JSON-RPC 消息：initialize · notifications/initialized · ping · tools/list · tools/call。
# 输出：stdout 每行一个响应（UTF-8）；通知不回；未知方法回 -32601；坏 JSON 回 -32700；工具内部错误回 -32603。
# 不做什么：零写接口——这个进程物理上写不了内容（只读 sqlite 连接）；不注入任何东西给驾驶员；不做 resources / prompts。
# 谁调用：驾驶员的 MCP 客户端（pilots/claude-code/.mcp.json · Codex 的 mcp 配置）· contact（初期接触第 2 步）· tests。
# 协议版本：回显客户端给的 protocolVersion（缺省 2025-06-18）；capabilities 只声明 tools。
# 工具入参：query（字符串或字符串列表）· scope（tools 默认 / corpus / all）· tool · kind · k（8 → 60）· per_doc（2 → 5）。
# 工具出参：content[0].text = 紧凑索引行 + 尾行「已显示 k/N」。段落用驾驶员自带的 Read 按 文件#L起-L止 取。
# serve(cfg, inp, out) 可注入流，测试不必起子进程；cli 用 sys.stdin.buffer / sys.stdout.buffer。
# 依赖：stdlib json · search。
import json, sys
from . import __version__, search

TOOL = {
    "name": "search",
    "description": "只读检索：默认查工具（词典 · 打法 · 记录），scope=corpus 查教材。收一条或多条查询（多组角度合并，round-robin，不重排），"
                   "返回紧凑索引行：id · 出处 · 文件#L起-L止 [位置] · kind · ≤120 字摘录，尾行「已显示 k/N」。段落用 Read 按行号取。",
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {"anyOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}], "description": "一条查询，或多组不同角度的查询"},
            "scope": {"type": "string", "enum": ["tools", "corpus", "all"], "default": "tools"},
            "tool": {"type": "string", "description": "只查某件装备"},
            "kind": {"type": "string", "description": "concept / method / playbook / record / material / corpus"},
            "k": {"type": "integer", "default": 8, "minimum": 1, "maximum": 60},
            "per_doc": {"type": "integer", "default": 2, "minimum": 1, "maximum": 5},
        },
        "required": ["query"],
    },
}


def handle(cfg, msg):
    """一条请求 → (result, error)。通知返回 (None, None)。"""
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
            return None, {"code": -32602, "message": "只有一个工具：search"}
        if not a.get("query"):
            return {"content": [{"type": "text", "text": "query 不能为空"}], "isError": True}, None
        res = search.search(cfg, a["query"], scope=a.get("scope", "tools"), tool=a.get("tool"), kind=a.get("kind"),
                            k=a.get("k", 8), per_doc=a.get("per_doc", 2))
        return {"content": [{"type": "text", "text": search.format_rows(res)}], "isError": False}, None
    return None, {"code": -32601, "message": "没有这个方法：%s" % m}


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
            send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "不是 JSON"}})
            continue
        try:
            result, error = handle(cfg, msg)
        except Exception as e:                       # 工具内部错误也要回给客户端，不能让进程死掉
            result, error = None, {"code": -32603, "message": "%s: %s" % (type(e).__name__, e)}
        if msg.get("id") is None:
            continue
        send({"jsonrpc": "2.0", "id": msg["id"], "error": error} if error else {"jsonrpc": "2.0", "id": msg["id"], "result": result})
    return 0
