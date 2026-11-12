# Verb check, records that carry a `due` day (D86): from that day one `due` WARNING until outcome is filled, and
# never the generic 30-day `outcome` WARNING for that record; before the day, nothing; filled, nothing. A record
# without `due` keeps the 30-day rule. The numbers page and the report count exactly what check warns about.
from datetime import date
from entryplug import check, report

TODAY = date(2026, 8, 29)
OLD = "self/records/2026-07-20-supplier-delay.md"          # 40 days old on TODAY, no outcome
SETTLED = "self/records/2026-08-21-counterpart-feigns-weakness.md"   # has an outcome


def put_due(root, rel, line):
    p = root / rel
    s = p.read_text(encoding="utf-8")
    assert "\noutcome:" in s
    p.write_text(s.replace("\noutcome:", "\n%s\noutcome:" % line, 1), encoding="utf-8")


def run(cfg):
    return check.run(cfg, expire=False, tool_checks=False, today=TODAY)


def owed(r, rel):
    return [(w["code"], w["msg"]) for w in r["warnings"] if w["file"] == rel and w["code"] in ("due", "outcome")]


def test_a_record_past_its_due_day_warns_due_and_not_outcome(repo):
    root = repo["root"]
    put_due(root, OLD, "due: 2026-08-18")
    r = run(repo)
    assert owed(r, OLD) == [("due", "record was due for settlement on 2026-08-18 (11 days ago) and has no outcome; "
                                    "settle it: fill outcome")], r["warnings"]
    assert "outcome pending 1" in r["numbers"]
    assert "outcome still open (due day reached, or >=30 days) 1: " + OLD in report.report(repo, r)
    p = root / OLD
    p.write_text(p.read_text(encoding="utf-8").replace("due: 2026-08-18", 'due: "2026-08-29"'), encoding="utf-8")
    assert owed(run(repo), OLD) == [("due", "record was due for settlement on 2026-08-29 (today) and has no outcome; "
                                            "settle it: fill outcome")]
    p.write_text(p.read_text(encoding="utf-8").replace('due: "2026-08-29"', "due: 2026-08-28"), encoding="utf-8")
    assert "(1 day ago)" in owed(run(repo), OLD)[0][1]


def test_before_its_due_day_a_record_owes_nothing_and_one_without_due_keeps_30_days(repo):
    root = repo["root"]
    put_due(root, OLD, "due: 2026-09-15")
    other = "self/records/2026-07-10-other-call.md"
    (root / other).write_text((root / OLD).read_text(encoding="utf-8").replace("due: 2026-09-15\n", ""), encoding="utf-8")
    r = run(repo)
    assert owed(r, OLD) == [], r["warnings"]                 # 40 days old, but its own date has not come
    assert owed(r, other) == [("outcome", "record has had no outcome for 50 days")]
    assert "outcome pending 1" in r["numbers"]                # the one check warns about, not the one not yet due
    assert "outcome still open (due day reached, or >=30 days) 1: " + other in report.report(repo, r)


def test_a_settled_record_with_a_past_due_day_owes_nothing(repo):
    root = repo["root"]
    put_due(root, SETTLED, "due: 2026-08-22")
    put_due(root, OLD, "due: 2026-08-01")
    p = root / OLD
    p.write_text(p.read_text(encoding="utf-8").replace("\noutcome:\n", "\noutcome: 它对：截止日前对方回了\n"), encoding="utf-8")
    r = run(repo)
    assert owed(r, SETTLED) == [] and owed(r, OLD) == [] and r["errors"] == [], r["warnings"]
    assert "outcome pending 0" in r["numbers"]
