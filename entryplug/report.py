# 做什么：把 check.run 的结果排成人读的文本——逐项清单（ERROR / WARNING · 文件 · 文案 · 核验时间戳）和一页报告
#         （头部自检 → 清单 → 本周记录 / 分歧 / 待批提议 / 待填结果 / 过期资料 / 孤立词条 → 同步率）。
# 输入：cfg · check.run() 返回的 dict。
# 输出：纯文本。永远没有总分、没有聚合分；每条带核验时间戳。
# 不做什么：不算任何东西（算在 check / numbers）；不写文件；不读内容仓库。
# 谁调用：cli（plug check 默认打印 report，--quiet 只打印 format_findings）· apply（回滚时打印 ERROR 清单）· tests。
# 分歧 = chosen 非空且不以「同意 / 同 / 按它」开头且 ≠ verdict（与 numbers.agrees 同一口径）。
# 「本周」= 记录年龄 ≤7 天；「待填结果」= outcome 空且 ≥30 天。
# 报告是主人想看时才跑的那一页（§9）；叙事版（做完了什么 / 说了要做没做）是读记录的活，不是机器的活。
# 依赖：无（纯格式化）。
from .numbers import agrees


def format_findings(r):
    lines = ["%s %s · %s · %s · 核验 %s" % (f["level"], f["code"], f["file"], f["msg"], f["at"]) for f in r["errors"] + r["warnings"]]
    return "\n".join(lines + ["ERROR %d · WARNING %d" % (len(r["errors"]), len(r["warnings"]))])


def report(cfg, r):
    h = r["header"]
    L = ["# plug check · %s · entryplug %s（钉 %s）· 形状 v%s %s" % (h["at"], h["machine"], h["machine_pin"] or "-", h["shape_version"], "✓" if h["shape_ok"] else "✗ 机器拒跑"),
         "索引：%s%s · 钩子：%s · 装备：%s" % (h["index_built"] or "无", "（过期）" if h["index_stale"] else "",
                                          " ".join("%s=%s" % (k, (v or "从未")[:16]) for k, v in h["hooks"].items()), ", ".join(h["tools"]) or "无"),
         "", format_findings(r)]
    if r["moved"]:
        L.append("移到 rejected/（30 天未批）：" + ", ".join(r["moved"]))
    recs = r["records"]
    week = [x["rel"] for x in recs if x["age"] <= 7]
    dis = [x["rel"] for x in recs if str(x["fm"].get("chosen") or "").strip() and not agrees(x["fm"])]
    pending = [p["rel"] for p in r["proposals"] if p["sub"] == "pending"]
    wait = [x["rel"] for x in recs if not x["fm"].get("outcome") and x["age"] >= 30]
    expired = [m["rel"] for m in r["materials"] if m.get("expired")]
    L += ["", "本周记录 %d：%s" % (len(week), ", ".join(week) or "-"), "分歧（verdict ≠ chosen）%d：%s" % (len(dis), ", ".join(dis) or "-"),
          "待批提议 %d：%s" % (len(pending), ", ".join(pending) or "-"), "待填结果（≥30 天）%d：%s" % (len(wait), ", ".join(wait) or "-"),
          "过期资料 %d：%s" % (len(expired), ", ".join(expired) or "-"), "孤立词条（无入链）%d：%s" % (len(r["orphans"]), ", ".join(r["orphans"]) or "-"),
          "", r["numbers"]]
    return "\n".join(L)
