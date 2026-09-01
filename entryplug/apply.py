# What: `plug apply <proposal>` — approve one refit request: verify the base short hash → land it as add / replace
#       / retire → plug check with 0 ERROR → git commit (the proposal sha goes in a trailer).
#       `--reject REASON` moves it to rejected/ with a reason line. `--dry-run` only shows the diff.
# In:   cfg · proposal path (relative to the content repo, or absolute). The proposal's 「改成什么」 section holds
#       one fenced code block = the whole new file; or its first line is `retire` (D03).
# Out:  the target file lands · the proposal moves to proposals/applied/ · one git commit (KB_APPROVE=1 is set
#       here and nowhere else); the diff and the result go to stdout; exit code 0 / 1.
# Not:  a base mismatch (the target has changed) is refused outright, never silently overwritten; a check ERROR
#       rolls everything back; directories are not approved (a new equipment draft in proposals/tools/ is mounted
#       into plug.yaml by the owner by hand). Approval is the owner's move: an agent environment is refused.
# Who:  the owner, in a terminal. A pilot has no business calling it — all a pilot may write is the proposal.
# Note: base (D02) = the git blob short hash of the target's current content (first 8 chars, same value as
#       `plug hash <file>` and `git hash-object`); a new file is written `base: new`. add / replace / retire
#       follow from whether the target exists and from the body (§5.1); retire = move to retired/ alongside it.
#       Commit message: `apply: <action> <target>` + blank line + `Proposal: <rel>` + `Proposal-Sha: <sha256[:12]>`.
# Deps: stdlib (difflib · hashlib · subprocess only for git) · shapes · index · check.
import difflib, hashlib, os, re, shutil, subprocess
from datetime import date
from pathlib import Path
from . import config, shapes

# Any of these in the environment means a coding agent is driving. Detected defensively: presence is enough,
# the value is not inspected, and an unknown future marker simply is not caught (the hard lock stays pre-commit).
AGENT_ENV = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT", "CLAUDE_CODE_SESSION_ID",
             "CODEX_SANDBOX", "CODEX_SANDBOX_NETWORK_DISABLED", "CODEX_THREAD_ID", "CURSOR_AGENT", "AIDER_CHAT")


def blob_hash(data):
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()[:8]


def agent_markers(env=None):
    """Which agent-environment markers are set right now."""
    env = os.environ if env is None else env
    return [k for k in AGENT_ENV if env.get(k)]


def owner_lines(proposal, indent=""):
    """The owner's copy-paste block, defined in exactly one place so the refusal, the check report, a proposal's
    footer and the map templates cannot drift apart. The chat form always carries --owner: `!` runs in the same
    environment as the pilot's own Bash tool, so a bare chat-form approval would be refused by owner_refusal —
    printing one would hand the owner a command that walls the moment he copies it."""
    return [indent + "in a terminal:  plug apply %s" % proposal,
            indent + '                plug apply %s --reject "reason"' % proposal,
            indent + "from the chat:  ! plug apply %s --owner" % proposal,
            indent + '                ! plug apply %s --reject "reason" --owner' % proposal,
            indent + "look first (anyone, anywhere):  plug apply %s --dry-run" % proposal]


def owner_refusal(proposal, owner=False, env=None):
    """None when this may run; otherwise the refusal text. --dry-run never reaches here."""
    env = os.environ if env is None else env
    if owner or env.get("PLUG_OWNER") == "1":
        return None
    seen = agent_markers(env)
    if not seen:
        return None
    return "\n".join([
        "apply: agent environment detected (%s) — approving or rejecting a refit request is the owner's move." % ", ".join(seen),
        "Owner, run one of these yourself (the chat form needs --owner: ! shares this very environment):",
        *owner_lines(proposal, indent="  "),
        "A pilot never passes --owner — that is the same broken promise as setting KB_APPROVE by hand.",
    ])


def parse_proposal(path):
    """→ {fm, text, content, retire, errors}. content = the whole-file fenced block (add/replace); None for retire."""
    text = path.read_text(encoding="utf-8")
    p = shapes.parse_file(text, "proposal")
    body = p["sections"].get("改成什么", "")
    first = next((l.strip() for l in body.splitlines() if l.strip()), "")
    m = re.search(r"```[\w-]*\n(.*?)\n```", body, re.S)
    out = {"fm": p["fm"], "text": text, "errors": list(p["errors"]), "content": None, "retire": first.lower() in ("retire", "退役")}
    if m and not out["retire"]:
        out["content"] = m.group(1) + "\n"
    elif not out["retire"]:
        out["errors"].append("「改成什么」holds no whole-file code block (```…```) and is not `retire` — the machine cannot land it; rewrite the proposal")
    return out


def _git(root, *args, env=None):
    return subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True, encoding="utf-8", env=env)


def run(cfg, proposal, reject=None, dry_run=False, owner=False):
    root = cfg["root"]
    ppath = (root / proposal) if not os.path.isabs(proposal) else Path(proposal)
    if not ppath.exists():
        print("apply: no such proposal %s" % proposal)
        return 1
    if not dry_run:
        refusal = owner_refusal(proposal, owner)
        if refusal:
            print(refusal)
            return 1
    prel = config.rel(cfg, ppath)
    if reject:
        dst = cfg["proposals_dir"] / "rejected" / ppath.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(ppath.read_text(encoding="utf-8").rstrip("\n") + "\n\nrejected: %s · %s\n" % (date.today(), reject), encoding="utf-8")
        ppath.unlink()
        print("rejected → %s" % config.rel(cfg, dst))
        return 0
    p = parse_proposal(ppath)
    if p["errors"]:
        print("apply: proposal is out of shape: " + "; ".join(p["errors"]))
        return 1
    target = (root / str(p["fm"]["target"])).resolve()
    if root not in target.parents or target.is_dir():
        print("apply: target must be a file inside the content repo: %s" % p["fm"]["target"])
        return 1
    trel, base = config.rel(cfg, target), str(p["fm"]["base"]).strip()
    current = target.read_bytes() if target.exists() else None
    if current is None and base not in ("new", "-"):
        print("apply: target %s does not exist but base is %s (a new file needs `base: new`) → refused" % (trel, base))
        return 1
    if current is not None and blob_hash(current) != base:
        print("apply: base mismatch — the proposal was written against %s, %s is now %s → refused, nothing overwritten; "
              "rewrite the proposal against the file as it stands" % (base, trel, blob_hash(current)))
        return 1
    action = "retire" if p["retire"] else ("add" if current is None else "replace")
    if action == "retire":
        if current is None:
            print("apply: the target to retire does not exist: %s" % trel)
            return 1
        dest = target.parent / "retired" / target.name
        print("retire: %s → %s" % (trel, config.rel(cfg, dest) if dest.parent.exists() else trel.replace(target.name, "retired/" + target.name)))
    else:
        old = current.decode("utf-8").splitlines() if current else []
        diff = difflib.unified_diff(old, p["content"].splitlines(), "a/" + trel, "b/" + trel, lineterm="")
        print("\n".join(diff) or "(identical content)")
    if dry_run:
        return 0
    if action == "retire":
        dest.parent.mkdir(exist_ok=True)
        shutil.move(str(target), str(dest))
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(p["content"].encode("utf-8"))
    from . import index, check, report
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
        print("apply: check found ERRORs, rolled back:\n" + report.format_findings({"errors": r["errors"], "warnings": []}))
        return 1
    applied = cfg["proposals_dir"] / "applied" / ppath.name
    applied.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(ppath), str(applied))
    index.build(cfg)                          # the proposal has left pending; the playbook directory must stop listing it
    psha = hashlib.sha256(p["text"].encode("utf-8")).hexdigest()[:12]
    env = dict(os.environ, KB_APPROVE="1")
    paths = [trel, prel, config.rel(cfg, applied)] + ([config.rel(cfg, dest)] if action == "retire" else [])
    if _git(root, "rev-parse", "--git-dir").returncode != 0:
        print("apply: landed (%s %s) but this is not a git repo, nothing committed. Proposal sha %s" % (action, trel, psha))
        return 0
    for path in paths:                       # add one at a time: a path that never existed would fail the whole add
        _git(root, "add", "-A", "--", path, env=env)
    msg = "apply: %s %s\n\nProposal: %s\nProposal-Sha: %s\n" % (action, trel, prel, psha)
    r = _git(root, "commit", "-q", "-m", msg, env=env)
    if r.returncode != 0:
        print("apply: landed but the commit failed: %s" % (r.stderr.strip() or r.stdout.strip()))
        return 1
    print("landed and committed: %s %s · proposal → %s · Proposal-Sha %s" % (action, trel, config.rel(cfg, applied), psha))
    return 0
