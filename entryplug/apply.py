# 做什么：`plug apply <proposal>`——批一条改装申请（提议）：核 base 短哈希 → add / replace / retire 落地 → plug check 0 ERROR → git 提交（trailer 记提议 sha）。
#         `--reject REASON` 驳回：移到 rejected/ 加一行理由。`--dry-run` 只看 diff。
# 输入：cfg · 提议路径（相对内容仓库或绝对）。提议正文「改成什么」含一个 fenced 代码块 = 整文件新内容；或第一行 `retire`（D03）。
# 输出：落地的目标文件 · 提议移到 proposals/applied/ · 一次 git 提交（KB_APPROVE=1 只在这里设）；stdout 打印 diff 与结果；退出码 0 / 1。
# 不做什么：base 不匹配（目标文件已变）整体拒绝，绝不静默覆盖；check 有 ERROR 就回滚；不批目录（proposals/tools/ 的新装备草案由主人手动挂进 plug.yaml）。
# 谁调用：主人（终端）。驾驶员没有理由调它——它写的只能是提议。
# base（D02）= 目标文件当前内容的 git blob 短哈希（前 8 位，`plug hash <file>` 或 `git hash-object` 同值）；新建文件写 `base: new`。
# add / replace / retire 由目标存在与否和正文推出（§5.1）；retire = 移到同目录 retired/。
# 提交信息：`apply: <action> <target>` + 空行 + `Proposal: <rel>` + `Proposal-Sha: <sha256 前 12 位>`。
# 依赖：stdlib（difflib · hashlib · subprocess 只为 git）· shapes · index · check。
import difflib, hashlib, os, re, shutil, subprocess
from datetime import date
from pathlib import Path
from . import config, shapes


def blob_hash(data):
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()[:8]


def parse_proposal(path):
    """→ {fm, text, action_hint, content, errors}。content = fenced 块整文件内容（add/replace）；retire 时为 None。"""
    text = path.read_text(encoding="utf-8")
    p = shapes.parse_file(text, "proposal")
    body = p["sections"].get("改成什么", "")
    first = next((l.strip() for l in body.splitlines() if l.strip()), "")
    m = re.search(r"```[\w-]*\n(.*?)\n```", body, re.S)
    out = {"fm": p["fm"], "text": text, "errors": list(p["errors"]), "content": None, "retire": first.lower() in ("retire", "退役")}
    if m and not out["retire"]:
        out["content"] = m.group(1) + "\n"
    elif not out["retire"]:
        out["errors"].append("「改成什么」里没有整文件代码块（```…```），也不是 retire——机器无法落地，请重写提议")
    return out


def _git(root, *args, env=None):
    return subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True, encoding="utf-8", env=env)


def run(cfg, proposal, reject=None, dry_run=False):
    root = cfg["root"]
    ppath = (root / proposal) if not os.path.isabs(proposal) else Path(proposal)
    if not ppath.exists():
        print("apply: 找不到提议 %s" % proposal)
        return 1
    prel = config.rel(cfg, ppath)
    if reject:
        dst = cfg["proposals_dir"] / "rejected" / ppath.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(ppath.read_text(encoding="utf-8").rstrip("\n") + "\n\nrejected: %s · %s\n" % (date.today(), reject), encoding="utf-8")
        ppath.unlink()
        print("已驳回 → %s" % config.rel(cfg, dst))
        return 0
    p = parse_proposal(ppath)
    if p["errors"]:
        print("apply: 提议不合形状：" + "；".join(p["errors"]))
        return 1
    target = (root / str(p["fm"]["target"])).resolve()
    if root not in target.parents or target.is_dir():
        print("apply: target 必须是内容仓库内的一个文件：%s" % p["fm"]["target"])
        return 1
    trel, base = config.rel(cfg, target), str(p["fm"]["base"]).strip()
    current = target.read_bytes() if target.exists() else None
    if current is None and base not in ("new", "-"):
        print("apply: 目标 %s 不存在，但 base 是 %s（新建文件应写 base: new）→ 拒绝" % (trel, base))
        return 1
    if current is not None and blob_hash(current) != base:
        print("apply: base 不匹配——提议基于 %s，当前 %s 是 %s → 拒绝，不覆盖；请对着现在的文件重写提议" % (base, trel, blob_hash(current)))
        return 1
    action = "retire" if p["retire"] else ("add" if current is None else "replace")
    if action == "retire":
        if current is None:
            print("apply: 要退役的目标不存在：%s" % trel)
            return 1
        dest = target.parent / "retired" / target.name
        print("retire: %s → %s" % (trel, config.rel(cfg, dest) if dest.parent.exists() else trel.replace(target.name, "retired/" + target.name)))
    else:
        old = current.decode("utf-8").splitlines() if current else []
        diff = difflib.unified_diff(old, p["content"].splitlines(), "a/" + trel, "b/" + trel, lineterm="")
        print("\n".join(diff) or "（内容相同）")
    if dry_run:
        return 0
    if action == "retire":
        dest.parent.mkdir(exist_ok=True)
        shutil.move(str(target), str(dest))
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(p["content"].encode("utf-8"))
    from . import index, check
    index.build(cfg)
    r = check.run(cfg, expire=False)
    if r["errors"]:
        if action == "retire":
            shutil.move(str(dest), str(target))
        elif current is None:
            target.unlink()
        else:
            target.write_bytes(current)
        index.build(cfg)
        print("apply: 体检有 ERROR，已回滚：\n" + check.format_findings({"errors": r["errors"], "warnings": []}))
        return 1
    applied = cfg["proposals_dir"] / "applied" / ppath.name
    applied.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(ppath), str(applied))
    index.build(cfg)                          # 提议已离开 pending，打法目录里的「待批」要跟着消失
    psha = hashlib.sha256(p["text"].encode("utf-8")).hexdigest()[:12]
    env = dict(os.environ, KB_APPROVE="1")
    paths = [trel, prel, config.rel(cfg, applied)] + ([config.rel(cfg, dest)] if action == "retire" else [])
    if _git(root, "rev-parse", "--git-dir").returncode != 0:
        print("apply: 已落地（%s %s），但不是 git 仓库，未提交。提议 sha %s" % (action, trel, psha))
        return 0
    for path in paths:                       # 逐个 add：不存在也没被跟踪过的路径会让整条 add 失败
        _git(root, "add", "-A", "--", path, env=env)
    msg = "apply: %s %s\n\nProposal: %s\nProposal-Sha: %s\n" % (action, trel, prel, psha)
    r = _git(root, "commit", "-q", "-m", msg, env=env)
    if r.returncode != 0:
        print("apply: 已落地但提交失败：%s" % (r.stderr.strip() or r.stdout.strip()))
        return 1
    print("已落地并提交：%s %s · 提议 → %s · Proposal-Sha %s" % (action, trel, config.rel(cfg, applied), psha))
    return 0
