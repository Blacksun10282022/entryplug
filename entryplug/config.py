# 做什么：找到内容仓库的 plug.yaml，解析成一个普通 dict，把相对路径落成绝对路径，列出内容文件。
# 输入：--root 参数 / 环境变量 PLUG_ROOT / 从当前目录向上找 plug.yaml。
# 输出：cfg dict（root · self · records · proposals · index · tools[] · outbound · pilots · protected …）；
#       walk(cfg) 给出每个内容文件的 {path, rel, area, tool, sub}。
# 不做什么：不校验内容（那是 check 的事）；不读任何内容文件的正文；不写文件。
# 谁调用：所有动词与三道闸门。
# 约定：plug.yaml 是内容仓库里唯一允许出现路径的地方；机器永远不知道内容仓库在哪，只认 root。
# 区域名（area）：rules · facts · style · record · manual · reading · playbook · dict · material · corpus · checks · proposal · numbers。
# 形状版本与机器版本钉在 entryplug/__init__.py；plug.yaml 里 `machine: entryplug 0.1.0` / `shape_version: 1` 引用它们。
# 依赖：stdlib + PyYAML。
import os, fnmatch
from pathlib import Path
import yaml
from . import __version__, SHAPE_VERSION

DEFAULTS = {
    "self": "self", "proposals": "proposals", "index": ".kb/index.sqlite",
    "index_md": "index.md", "numbers": "self/数字.md", "hooks": ".kb/hooks", "pin": ".kb/pin.md",
    "language": "中文", "pilots": {"claude-code": {"skills": ".claude/skills"}, "codex": {"skills": ".agents/skills"}},
    "protected": ["self/RULES.md", "self/facts/**", "tools/**"], "unprotected": ["**/corpus/**"],
    "outbound": [], "tools": [],
}
PROPOSAL_DIRS = ("pending", "rejected", "applied", "tools")


def find_root(start=None):
    """PLUG_ROOT 优先；否则从 start（默认 cwd）向上找 plug.yaml。找不到抛 FileNotFoundError。"""
    env = os.environ.get("PLUG_ROOT")
    if env and (Path(env) / "plug.yaml").exists():
        return Path(env).resolve()
    p = Path(start or os.getcwd()).resolve()
    for d in (p, *p.parents):
        if (d / "plug.yaml").exists():
            return d
    raise FileNotFoundError("找不到 plug.yaml（用 --root 指定内容仓库，或设 PLUG_ROOT）")


def load(root=None):
    """读 plug.yaml → cfg。相对路径全部相对 root；tools 每项补齐 name/path/depends/ttl_days。"""
    root = Path(root).resolve() if root else find_root()
    raw = yaml.safe_load((root / "plug.yaml").read_text(encoding="utf-8")) or {}
    cfg = dict(DEFAULTS)
    cfg.update({k: v for k, v in raw.items() if v is not None})
    cfg["root"] = root
    cfg["self_dir"] = root / cfg["self"]
    cfg["records_dir"] = cfg["self_dir"] / "records"
    cfg["proposals_dir"] = root / cfg["proposals"]
    cfg["index_path"] = root / cfg["index"]
    cfg["index_md_path"] = root / cfg["index_md"]
    cfg["numbers_path"] = root / cfg["numbers"]
    cfg["hooks_dir"] = root / cfg["hooks"]
    cfg["pin_path"] = root / cfg["pin"]
    cfg["machine_pin"] = str(raw.get("machine", "")).strip()
    cfg["shape_version"] = raw.get("shape_version")
    tools = []
    for t in raw.get("tools") or []:
        t = dict(t)
        t.setdefault("path", f"tools/{t['name']}")
        t["dir"] = root / t["path"]
        t.setdefault("depends", [])
        t.setdefault("ttl_days", {})
        tools.append(t)
    cfg["tools"] = tools
    return cfg


def version_ok(cfg):
    """形状版本机器认不认识；机器版本钉住的是不是当前装的。返回 (shape_ok, machine_ok)。"""
    shape_ok = cfg.get("shape_version") == SHAPE_VERSION
    pin = cfg.get("machine_pin", "")
    machine_ok = (not pin) or pin.split()[-1] == __version__
    return shape_ok, machine_ok


def rel(cfg, path):
    return Path(path).resolve().relative_to(cfg["root"]).as_posix()


def is_protected(cfg, relpath):
    """受保护路径（暴走封锁）：protected 匹配且 unprotected 不匹配。glob 用 fnmatch，** 视作任意深度。"""
    def hit(patterns):
        for pat in patterns:
            if fnmatch.fnmatch(relpath, pat) or fnmatch.fnmatch(relpath, pat.replace("**/", "")):
                return True
            if pat.endswith("/**") and relpath.startswith(pat[:-3] + "/"):
                return True
        return False
    return hit(cfg["protected"]) and not hit(cfg["unprotected"])


def _md_files(d):
    return sorted(p for p in d.glob("*.md") if p.is_file()) if d.is_dir() else []


def walk(cfg):
    """列出所有内容文件。每项：path · rel · area · tool · sub。教材含 .md/.txt；其余只认 .md。"""
    out, root, s = [], cfg["root"], cfg["self_dir"]
    def add(path, area, tool=None, sub=None):
        out.append({"path": path, "rel": path.relative_to(root).as_posix(), "area": area, "tool": tool, "sub": sub})
    if (s / "RULES.md").exists():
        add(s / "RULES.md", "rules")
    if (s / "style.md").exists():
        add(s / "style.md", "style")
    for p in _md_files(s / "facts"):
        add(p, "facts")
    for p in _md_files(s / "records"):
        add(p, "record")
    for t in cfg["tools"]:
        d, n = t["dir"], t["name"]
        if (d / "SKILL.md").exists():
            add(d / "SKILL.md", "manual", n)
        if (d / "READING.md").exists():
            add(d / "READING.md", "reading", n)
        for p in _md_files(d / "playbooks"):
            if p.name != "INDEX.md":
                add(p, "playbook", n)
        for p in _md_files(d / "dict"):
            add(p, "dict", n)
        for p in _md_files(d / "materials"):
            add(p, "material", n)
        for sub in ("clean", "raw"):
            cd = d / "corpus" / sub
            if cd.is_dir():
                for p in sorted(cd.rglob("*")):
                    if p.is_file() and p.suffix.lower() in (".md", ".txt"):
                        add(p, "corpus", n, sub)
        for p in sorted((d / "checks").glob("*.py")) if (d / "checks").is_dir() else []:
            add(p, "checks", n)
    for sub in PROPOSAL_DIRS:
        pd = cfg["proposals_dir"] / sub
        if pd.is_dir():
            for p in sorted(pd.rglob("*.md")):
                add(p, "proposal", None, sub)
    return out
