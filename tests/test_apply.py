# 动词 apply：核 base（不匹配就拒，绝不覆盖）· add / replace / retire · 体检有 ERROR 回滚 · 提交带 Proposal-Sha · 驳回 · dry-run · hash。
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
    assert r.returncode == 1 and "base 不匹配" in r.stdout and "拒绝" in r.stdout
    assert p.read_bytes() == before and (root / PENDING).exists()


def test_add_and_rollback_on_check_error(git_repo):
    root = git_repo["root"]
    bad = proposal(root, "2026-08-29-bad.md", "tools/sunzi/dict/bad.md", "new", entry("坏词", "bad1, bad2", "[[不存在]]"))
    r = plug(root, "apply", str(bad.relative_to(root)))
    assert r.returncode == 1 and "回滚" in r.stdout and not (root / "tools/sunzi/dict/bad.md").exists() and bad.exists()
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
    assert r.returncode == 1 and "回滚" in r.stdout and (root / "tools/sunzi/dict/fan-jian.md").exists()
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
    assert r.returncode == 1 and "无法落地" in r.stdout
    r = plug(root, "apply", PENDING, "--reject", "反证成立")
    assert r.returncode == 0 and not (root / PENDING).exists()
    assert "rejected: " in (root / "proposals/rejected/2026-08-26-shi-alias.md").read_text(encoding="utf-8")
    r = plug(root, "hash", str(root / "tools/sunzi/dict/shi.md"))
    assert r.stdout.strip() == apply.blob_hash((root / "tools/sunzi/dict/shi.md").read_bytes()) == "3d42b9a9"
    assert git(root, "hash-object", "tools/sunzi/dict/shi.md").stdout.startswith("3d42b9a9")


def test_apply_without_git_lands_but_reports(repo):
    r = plug(repo["root"], "apply", PENDING)
    assert r.returncode == 0 and "未提交" in r.stdout and "势头" in (repo["root"] / "tools/sunzi/dict/shi.md").read_text(encoding="utf-8")
