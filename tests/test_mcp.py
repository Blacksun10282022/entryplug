# MCP：stdio JSON-RPC 的四个方法；唯一工具 search；中文查询非零；坏 JSON / 未知方法 / 内部错误都回错误而不是死掉；子进程也能通。
import io, json, subprocess, sys
from entryplug import mcp
from conftest import ROOT


def talk(cfg, msgs):
    inp = io.BytesIO("".join(json.dumps(m, ensure_ascii=False) + "\n" for m in msgs).encode("utf-8"))
    out = io.BytesIO()
    assert mcp.serve(cfg, inp, out) == 0
    return [json.loads(l) for l in out.getvalue().decode("utf-8").splitlines()]


def test_handshake_list_and_call(repo):
    res = talk(repo, [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "search", "arguments": {"query": "诡道", "k": 2}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "search", "arguments": {"query": ["以迂为直", "反间"], "scope": "corpus"}}},
        {"jsonrpc": "2.0", "id": 5, "method": "ping"},
    ])
    assert [r["id"] for r in res] == [1, 2, 3, 4, 5]
    assert res[0]["result"]["serverInfo"]["name"] == "entryplug" and res[0]["result"]["protocolVersion"] == "2025-06-18"
    assert [t["name"] for t in res[1]["result"]["tools"]] == ["search"] and "query" in res[1]["result"]["tools"][0]["inputSchema"]["required"]
    text = res[2]["result"]["content"][0]["text"]
    assert text.startswith("gui-dao · 诡道") and "已显示 2/" in text and res[2]["result"]["isError"] is False
    assert "sunzi-07-junzheng#1" in res[3]["result"]["content"][0]["text"]
    assert res[4]["result"] == {}


def test_errors_do_not_kill_the_server(repo):
    inp = io.BytesIO(('{"jsonrpc":"2.0","id":1,"method":"nope"}\nnot json\n{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"other","arguments":{}}}\n'
                      '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"search","arguments":{"query":""}}}\n'
                      '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"search","arguments":{"query":"势","k":"many"}}}\n'
                      '{"jsonrpc":"2.0","id":5,"method":"ping"}\n').encode("utf-8"))
    out = io.BytesIO()
    mcp.serve(repo, inp, out)
    res = [json.loads(l) for l in out.getvalue().decode("utf-8").splitlines()]
    assert res[0]["error"]["code"] == -32601 and res[1]["error"]["code"] == -32700 and res[2]["error"]["code"] == -32602
    assert res[3]["result"]["isError"] is True and res[4]["error"]["code"] == -32603 and res[5]["result"] == {}


def test_subprocess_stdio_roundtrip(repo):
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "search", "arguments": {"query": "虚实", "scope": "corpus", "k": 3}}}]
    p = subprocess.run([sys.executable, "-m", "entryplug.cli", "--root", str(repo["root"]), "mcp"], cwd=str(ROOT),
                       input="".join(json.dumps(m) + "\n" for m in msgs).encode("utf-8"), capture_output=True, timeout=60)
    lines = [json.loads(l) for l in p.stdout.decode("utf-8").splitlines()]
    assert lines[0]["result"]["serverInfo"]["version"] and "sunzi-06-xushi" in lines[1]["result"]["content"][0]["text"]
