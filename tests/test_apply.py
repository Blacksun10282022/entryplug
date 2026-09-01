# Verb apply: verify base (a mismatch is refused, never overwritten) · add / replace / retire · a check ERROR
# rolls back · the commit carries Proposal-Sha · reject · dry-run · hash · the owner-only gate.
from entryplug import apply
from conftest import git, plug

PENDING = "proposals/pending/2026-08-26-shi-alias.md"


def proposal(root, name, target, base, body):
    p = root / "proposals/pending" / name
    p.write_text("---\ntarget: %s\nbase: %s\nfrom: records/2026-08-27-choose-venue.md\n---\n## 改成什么\n%s\n## 为什么\nw\n## 最强反证\nc\n" % (target, base, body), encoding="utf-8")
    return p


def entry(title, aliases, links="[[势]] [[形]]"):
    return "```md\n---\nkind: concept\ntitle: %s\naliases: [%s]\n---\n## 定义\nx %s\n\n## 观察\n- 一句 ^p0801 (src: sunzi-01-shiji#3 \"兵者，诡道也\")\n\n## 关系\n- %s\n```" % (title, aliases, links, links)


def test_replace_commits_with_proposal_trailer(git_repo):
    root = git_repo["root"]
    r = plug(root, "apply", PENDING)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "势头" in (root / "tools/sunzi/dict/shi.md").read_text(encoding="utf-8")
    assert not (root / PENDING).exists() and (root / "proposals/applied/2026-08-26-shi-alias.md").exists()
    log = git(root, "log", "-1", "--format=%B").stdout
    assert log.startswith("apply: replace tools/sunzi/dict/shi.md") and "Proposal-Sha: " in log and "Proposal: " + PENDING in log
    assert git(root, "status", "--porcelain", "--", "tools", "proposals").stdout.strip() == ""


def test_base_mismatch_is_rejected_without_overwrite(git_repo):
    root = git_repo["root"]
    p = root / "tools/sunzi/dict/shi.md"
    p.write_text(p.read_text(encoding="utf-8") + "\n主人手改了一行。\n", encoding="utf-8")
    before = p.read_bytes()
    r = plug(root, "apply", PENDING)
    assert r.returncode == 1 and "base mismatch" in r.stdout and "refused" in r.stdout
    assert p.read_bytes() == before and (root / PENDING).exists()


def test_add_and_rollback_on_check_error(git_repo):
    root = git_repo["root"]
    bad = proposal(root, "2026-08-29-bad.md", "tools/sunzi/dict/bad.md", "new", entry("坏词", "bad1, bad2", "[[不存在]]"))
    r = plug(root, "apply", str(bad.relative_to(root)))
    assert r.returncode == 1 and "rolled back" in r.stdout and not (root / "tools/sunzi/dict/bad.md").exists() and bad.exists()
    good = proposal(root, "2026-08-29-good.md", "tools/sunzi/dict/good.md", "new", entry("好词", "good1, good2"))
    r = plug(root, "apply", str(good.relative_to(root)))
    assert r.returncode == 0, r.stdout
    assert (root / "tools/sunzi/dict/good.md").read_text(encoding="utf-8").startswith("---\nkind: concept\ntitle: 好词")
    assert "apply: add tools/sunzi/dict/good.md" in git(root, "log", "-1", "--format=%s").stdout
    wrong = proposal(root, "2026-08-29-wrong.md", "tools/sunzi/dict/new2.md", "3d42b9a9", entry("词", "a, b"))
    assert plug(root, "apply", str(wrong.relative_to(root))).returncode == 1


def test_retire_rolls_back_when_links_break_and_works_for_playbook(git_repo):
    root = git_repo["root"]
    h = apply.blob_hash((root / "tools/sunzi/dict/fan-jian.md").read_bytes())
    p = proposal(root, "2026-08-29-retire-fanjian.md", "tools/sunzi/dict/fan-jian.md", h, "retire")
    r = plug(root, "apply", str(p.relative_to(root)))
    assert r.returncode == 1 and "rolled back" in r.stdout and (root / "tools/sunzi/dict/fan-jian.md").exists()
    h = apply.blob_hash((root / "tools/sunzi/playbooks/choose-battlefield.md").read_bytes())
    p = proposal(root, "2026-08-29-retire-pb.md", "tools/sunzi/playbooks/choose-battlefield.md", h, "退役")
    r = plug(root, "apply", str(p.relative_to(root)))
    assert r.returncode == 0, r.stdout
    assert (root / "tools/sunzi/playbooks/retired/choose-battlefield.md").exists() and not (root / "tools/sunzi/playbooks/choose-battlefield.md").exists()
    assert "choose-battlefield" not in (root / "tools/sunzi/playbooks/INDEX.md").read_text(encoding="utf-8")


def test_reject_dry_run_prose_and_hash(git_repo):
    root = git_repo["root"]
    r = plug(root, "apply", PENDING, "--dry-run")
    assert r.returncode == 0 and "+aliases: [势能, 态势, 任势, 势头" in r.stdout and (root / PENDING).exists()
    prose = proposal(root, "2026-08-29-prose.md", "tools/sunzi/dict/shi.md", "3d42b9a9", "aliases 加一个词。")
    r = plug(root, "apply", str(prose.relative_to(root)))
    assert r.returncode == 1 and "cannot land it" in r.stdout
    r = plug(root, "apply", PENDING, "--reject", "反证成立")
    assert r.returncode == 0 and not (root / PENDING).exists()
    assert "rejected: " in (root / "proposals/rejected/2026-08-26-shi-alias.md").read_text(encoding="utf-8")
    r = plug(root, "hash", str(root / "tools/sunzi/dict/shi.md"))
    assert r.stdout.strip() == apply.blob_hash((root / "tools/sunzi/dict/shi.md").read_bytes()) == "3d42b9a9"
    assert git(root, "hash-object", "tools/sunzi/dict/shi.md").stdout.startswith("3d42b9a9")


def test_apply_without_git_lands_but_reports(repo):
    r = plug(repo["root"], "apply", PENDING)
    assert r.returncode == 0 and "nothing committed" in r.stdout and "势头" in (repo["root"] / "tools/sunzi/dict/shi.md").read_text(encoding="utf-8")


def test_apply_refuses_in_an_agent_environment(git_repo):
    """Approving is the owner's move. --dry-run stays open to everyone; --owner (or PLUG_OWNER=1) is the escape
    hatch the refusal itself prints, because the ! prefix shares the agent's environment."""
    root = git_repo["root"]
    agent = {"CLAUDECODE": "1"}
    r = plug(root, "apply", PENDING, env=agent)
    assert r.returncode == 1 and "agent environment detected (CLAUDECODE)" in r.stdout
    assert "--owner" in r.stdout and "--dry-run" in r.stdout and (root / PENDING).exists()
    r = plug(root, "apply", PENDING, "--reject", "no", env=agent)
    assert r.returncode == 1 and (root / PENDING).exists()
    r = plug(root, "apply", PENDING, "--dry-run", env=agent)
    assert r.returncode == 0 and "+aliases: [势能" in r.stdout and (root / PENDING).exists()
    r = plug(root, "apply", PENDING, env={"CODEX_SANDBOX": "seatbelt"})
    assert r.returncode == 1 and "CODEX_SANDBOX" in r.stdout
    r = plug(root, "apply", PENDING, env=dict(agent, PLUG_OWNER="1"))
    assert r.returncode == 0 and not (root / PENDING).exists()


def test_apply_runs_normally_with_the_owner_flag(git_repo):
    root = git_repo["root"]
    r = plug(root, "apply", PENDING, "--owner", env={"CLAUDECODE": "1", "CLAUDE_CODE_ENTRYPOINT": "cli"})
    assert r.returncode == 0, r.stdout + r.stderr
    assert not (root / PENDING).exists() and "势头" in (root / "tools/sunzi/dict/shi.md").read_text(encoding="utf-8")
def test_the_copy_paste_block_survives_its_own_gate(git_repo):
    """The block the owner is handed must work when he copies it. The chat form runs in the pilot's environment,
    so it has to carry --owner; the terminal form must not. Regression for the one command that walled."""
    from entryplug import apply as A
    lines = A.owner_lines(PENDING)
    chat = [l for l in lines if "!" in l]
    terminal = [l for l in lines if "!" not in l and "--dry-run" not in l]
    assert len(chat) == 2 and all("--owner" in l for l in chat), lines
    assert len(terminal) == 2 and not any("--owner" in l for l in terminal), lines
    assert any("--dry-run" in l and "--owner" not in l for l in lines)
    agent = {"CLAUDECODE": "1"}
    assert plug(git_repo["root"], "apply", PENDING, "--reject", "no", "--owner", env=agent).returncode == 0
    assert not (git_repo["root"] / PENDING).exists()


def test_no_tracked_file_prints_a_chat_command_the_gate_would_refuse():
    """Scan every tracked text file: an exclamation-prefixed apply must carry --owner (or be a --dry-run), or the
    owner copies it and hits the refusal. Catches a template, a footer or a doc drifting away from owner_lines()."""
    import re, subprocess
    from conftest import ROOT
    pat = re.compile(r"!\s*plug\s+" + "apply" + r"\s+\S+([^\n]*)")
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=str(ROOT),
                         capture_output=True, text=True, encoding="utf-8").stdout
    bad = []
    for rel in [f for f in out.split("\n") if f.strip().endswith((".md", ".py", ".json", ".yaml", ".toml"))]:
        f = ROOT / rel
        if not f.is_file():
            continue
        for n, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for m in pat.finditer(line):
                if "--owner" not in m.group(1) and "--dry-run" not in m.group(1):
                    bad.append("%s:%d %s" % (rel, n, line.strip()))
    assert not bad, bad
