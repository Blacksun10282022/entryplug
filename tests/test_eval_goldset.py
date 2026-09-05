# The public gold set is a real, reproducible metric: it must keep clearing a recall floor on the example
# equipment, and Chinese recall must never collapse to zero (the failure §6.1 exists to catch). These run
# against a fresh temporary copy of example-tool (the `repo` fixture copies without .kb and re-indexes), so a
# clean checkout on any platform gives the same answer and example-tool/.kb is never touched.
#
# THRESHOLD is the measured overall recall@10 minus a 0.05 margin. Measured 2026-09-05 on example-tool: overall
# 0.98 (n=50), zh 0.96 (n=28), en 1.00 (n=22); the one miss is the deliberate homophone typo zh-typo-01. If a
# real content or tokenizer change moves the number, re-measure and reset the floor here on purpose — do not
# delete cases to lift the score.
import re
import sqlite3
import yaml
from conftest import ROOT
from entryplug import eval as ev

GOLD = ROOT / "bench" / "public" / "goldset-sunzi.yaml"
THRESHOLD = 0.93


def _load_cases():
    g = yaml.safe_load(GOLD.read_text(encoding="utf-8")) or {}
    return g.get("cases") or []


def _summary(out):
    """The one line that starts with 'recall@10' (per-case lines carry it mid-line)."""
    return [l for l in out.splitlines() if l.startswith("recall@10")][0]


def test_public_goldset_clears_floor(repo, capsys):
    rc = ev.run(repo, str(GOLD))
    out = capsys.readouterr().out
    assert "ERROR" not in out, out
    assert rc == 0, out                                     # eval exits 1 iff Chinese recall is zero (§6.1)

    line = _summary(out)
    overall = float(re.search(r"^recall@10 ([0-9.]+)", line).group(1))
    n = int(re.search(r"n=(\d+)", line).group(1))
    zh_str, zh_n = re.search(r"zh (\S+) \(n=(\d+)\)", line).groups()
    en_str, en_n = re.search(r"en (\S+) \(n=(\d+)\)", line).groups()
    zh = float(zh_str) if zh_str != "-" else 0.0
    en = float(en_str) if en_str != "-" else 0.0

    assert n == len(_load_cases()), "eval ran %d cases, the gold set has %d" % (n, len(_load_cases()))
    assert overall >= THRESHOLD, "overall recall@10 %.2f fell below the %.2f floor\n%s" % (overall, THRESHOLD, out)
    assert zh > 0, "Chinese recall is zero — the tokenizer or index is broken\n%s" % out
    assert int(zh_n) >= 20 and int(en_n) >= 15, "expected a Chinese/English split, got zh n=%s en n=%s" % (zh_n, en_n)
    assert en > 0


def test_every_expected_id_exists_in_index(repo):
    """Guard against id rot: every id a case expects (typo cases included — they expect a real doc, they just
    fail to retrieve it) must exist in the index as a corpus doc id, an entry/row id, or a chunk id."""
    con = sqlite3.connect("file:%s?mode=ro" % repo["index_path"].as_posix(), uri=True)
    docs = {r[0] for r in con.execute("select distinct doc from fts")}
    ids = {r[0] for r in con.execute("select distinct id from fts")}
    con.close()
    universe = docs | ids
    missing = []
    for c in _load_cases():
        for want in (c.get("expect") or []):
            if str(want) not in universe:
                missing.append((c.get("id", c.get("q")), want))
    assert not missing, "gold-set expects ids not present in the index: %s" % missing
