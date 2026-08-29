# STATUS

最后在 Claude Code vX / Codex vY 上验证通过：**尚未**——真机里的四合一（deny 拒 Edit、bypass 下仍拒、压缩后接着做、切换驾驶员）是验收剧本的 MANUAL 项（C1.2 / C2.3 / C3.3 / C4.4），等主人在自己的驾驶员里跑一次后把版本号填进这一行。

构建机上装着 Claude Code 2.1.251 与 codex-cli 0.128.0（`plug check --contact` 读到的版本戳）；初期接触四步在示例装备的临时副本上两边全绿（说明书镜像 · MCP 中文查询非零 · 假对外动作被拦 · pre-commit 拒受保护写入 + deny 规则文件核）。

机器本身：2026-08-29 · Windows 11 · Python 3.12.4 · SQLite 3.45.3（FTS5）· git 2.51 · jieba 0.42.1 —— `python -m pytest` 全过；`python tests/acceptance.py` 自动项全 PASS（示例装备）。

只在自己的验收剧本全过时打 tag。当前没有 tag。
