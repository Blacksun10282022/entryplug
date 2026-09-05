# Verb eval: the public mini gold set scores non-zero on the example and zh is in the same league as en;
# zero recall on Chinese is an ERROR (exit 1); every field of the gold-set format is understood.
from conftest import ROOT, plug

GOLD = ROOT / "bench" / "public" / "goldset-sunzi.yaml"


def test_public_goldset_on_example(repo):
    r = plug(repo["root"], "eval", str(GOLD))
    assert r.returncode == 0, r.stdout
    tail = [l for l in r.stdout.splitlines() if l.startswith("recall@10")][0]
    assert "zh " in tail and "en " in tail and "ERROR" not in r.stdout
    scores = {l.split()[0]: float(l.split("recall@10 ")[1].split()[0]) for l in r.stdout.splitlines() if "recall@10 " in l and not l.startswith("recall@10")}
    assert scores["zh-01"] == 1.0 and scores["zh-11"] == 1.0 and scores["en-01"] == 1.0 and scores["zh-13"] == 1.0
    zh = [v for k, v in scores.items() if k.startswith("zh-") and "typo" not in k]
    assert sum(zh) / len(zh) >= 0.9      # mean over however many non-typo zh cases the set holds (was hard-coded /20)


def test_chinese_zero_is_error(repo, tmp_path):
    g = tmp_path / "g.yaml"
    g.write_text("version: 1\nscope: corpus\ncases:\n  - {id: a, q: 这个词肯定不在教材里面出现过吧, expect: [sunzi-01-shiji]}\n  - {id: b, q: deception, scope: tools, expect: [gui-dao]}\n", encoding="utf-8")
    r = plug(repo["root"], "eval", str(g))
    assert r.returncode == 1 and "ERROR recall on Chinese queries is zero" in r.stdout
    g.write_text("version: 1\ncases:\n  - {q: 诡道, expect: [sunzi-01-shiji], lang: zh, per_doc: 2}\n  - {q: [势, 形], scope: tools, expect: [shi, xing]}\n", encoding="utf-8")
    r = plug(repo["root"], "eval", str(g), "--k", "5")
    assert r.returncode == 0 and "recall@5 1.00" in r.stdout
    g.write_text("version: 1\ncases: []\n", encoding="utf-8")
    assert plug(repo["root"], "eval", str(g)).returncode == 1
