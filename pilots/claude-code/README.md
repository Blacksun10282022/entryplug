# pilots/claude-code · Claude Code 接入

薄壳，不含任何内容。最短路径：在内容仓库里跑 `plug init --pilot claude-code`——它做完下面 A 的 1–5（真实绝对路径、合并不覆盖、幂等），然后 `plug index`、`plug check --contact claude-code`。手动装法如下：

**A. 项目级（推荐，内容仓库自带）**
1. `pilots/claude-code/CLAUDE.md` → 复制为 `<内容仓库>/CLAUDE.md`，填 `<tool-…>`。
2. `settings.template.json` → 合进 `<内容仓库>/.claude/settings.json`，把 `//c/<content-repo>`、`//c/<entryplug-repo>` 换成绝对路径。
3. `.mcp.json` → 复制到 `<内容仓库>/.mcp.json`（`plug` 要在 PATH：`pip install -e <entryplug>`）。
4. `plug index` 会把每件装备的 `SKILL.md` 镜像到 `<内容仓库>/.claude/skills/<装备>/SKILL.md`。
5. `gates/hooks/pre-commit` → `<内容仓库>/.git/hooks/pre-commit`。
6. `plug check --contact claude-code` 四步全绿。

**B. 插件形式**：本目录就是一个插件根（`.claude-plugin/plugin.json` + `hooks/hooks.json` + `.mcp.json`），`claude plugin add <本目录>`；deny 规则和 pre-commit 仍按 A 的 2、5 装到内容仓库（插件装不了 deny）。

## 记住三件事

- deny 只认 `Edit()` / `Read()`；`Write()` 规则从不被检查。不要 deny `Read(self/RULES.md)`——驾驶员得读规则。
- deny 在 bypassPermissions 下也生效，但挡不住 `python -c` 直写；兜底是 pre-commit。
- 升级 Claude Code 当天跑 `plug check --contact claude-code`；换模型跑一遍 `tests/acceptance.py`。
