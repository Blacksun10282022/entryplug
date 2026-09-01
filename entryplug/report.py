# What: lay out check.run's result for a human — the findings list (ERROR / WARNING · file · text · verified at)
#       and the one-page report (header self-check → findings → records this week / disagreements / pending
#       proposals / outcomes still open / expired materials / orphan entries → sync rate).
# In:   cfg · the dict returned by check.run().
# Out:  plain text. Never a total, never an aggregate score; every line carries the time it was verified.
# Not:  computes nothing (that is check / numbers); writes no files; reads no content repo.
# Who:  cli (plug check prints the report; --quiet prints only format_findings) · apply (findings on rollback) · tests.
# Note: a disagreement = chosen is non-empty, does not start with one of the owner's assent words and differs
#       from verdict (the same rule as numbers.agrees). "This week" = record age <= 7 days; "outcome still open"
#       = outcome empty and age >= 30. The report is the page the owner asks for (§9); the narrative version
#       (what got done, what was promised and not done) is reading the records, not the machine's job.
# Deps: numbers.agrees (the same rule for a disagreement) · apply.owner_lines (one source for the copy-paste block).
from .numbers import agrees
from .apply import owner_lines


def format_findings(r):
    lines = ["%s %s · %s · %s · verified %s" % (f["level"], f["code"], f["file"], f["msg"], f["at"]) for f in r["errors"] + r["warnings"]]
    return "\n".join(lines + ["ERROR %d · WARNING %d" % (len(r["errors"]), len(r["warnings"]))])


def report(cfg, r):
    h = r["header"]
    L = ["# plug check · %s · entryplug %s (pinned %s) · shape v%s %s" % (h["at"], h["machine"], h["machine_pin"] or "-", h["shape_version"], "OK" if h["shape_ok"] else "unknown, machine refuses to run"),
         "index: %s%s · hooks: %s · equipment: %s%s" % (h["index_built"] or "none", " (stale)" if h["index_stale"] else "",
                                                        " ".join("%s=%s" % (k, (v or "never")[:16]) for k, v in h["hooks"].items()),
                                                        ", ".join(h["tools"]) or "none",
                                                        " · .plug-off present (sortie lock, pin and record reminder pass through)" if h.get("plug_off") else ""),
         "", format_findings(r)]
    if r["moved"]:
        L.append("moved to rejected/ (30 days unapproved): " + ", ".join(r["moved"]))
    recs = r["records"]
    week = [x["rel"] for x in recs if x["age"] <= 7]
    dis = [x["rel"] for x in recs if str(x["fm"].get("chosen") or "").strip() and not agrees(x["fm"])]
    pending = [p["rel"] for p in r["proposals"] if p["sub"] == "pending"]
    wait = [x["rel"] for x in recs if not x["fm"].get("outcome") and x["age"] >= 30]
    expired = [m["rel"] for m in r["materials"] if m.get("expired")]
    L += ["", "records this week %d: %s" % (len(week), ", ".join(week) or "-"),
          "disagreements (verdict != chosen) %d: %s" % (len(dis), ", ".join(dis) or "-"),
          "pending proposals %d: %s" % (len(pending), ", ".join(pending) or "-"),
          "outcome still open (>=30 days) %d: %s" % (len(wait), ", ".join(wait) or "-"),
          "expired materials %d: %s" % (len(expired), ", ".join(expired) or "-"),
          "orphan entries (no inbound link) %d: %s" % (len(r["orphans"]), ", ".join(r["orphans"]) or "-")]
    for rel in pending:                       # the owner's copy-paste block, one per pending proposal
        L += owner_lines(rel, indent="  ")
    L += ["", r["numbers"]]
    return "\n".join(L)
