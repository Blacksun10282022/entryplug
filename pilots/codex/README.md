# pilots/codex · Codex 零代码接入

两个驾驶员平权：一切状态都是内容仓库里的文件，切换 = 换个人读同一个文件夹。

1. `AGENTS.md` → 复制为 `<内容仓库>/AGENTS.md`，填 `<tool-…>`（和 CLAUDE.md 是同一份地图）。
2. 说明书：`plug index` 已把每件装备的 `SKILL.md` 镜像到 `<内容仓库>/.agents/skills/<装备>/SKILL.md`，并放好 `agents/openai.yaml`（`allow_implicit_invocation: true`，Codex 的隐式调用开关不在 frontmatter，见 `agents-openai.yaml`）。
   想只留一份副本，也可以用目录链接代替镜像（Windows）：`mklink /J .agents\skills .claude\skills`，然后在 plug.yaml 里删掉 codex 的 skills 行。
3. MCP：在 Codex 的 MCP 配置里加一条 `entryplug`，命令 `plug mcp`（cwd = 内容仓库）。
4. 出击封锁：`hooks.json` → 合进 `~/.codex/hooks.json`（或仓库级），改占位路径；每个钩子首次要手动信任。
5. 暴走封锁：`gates/hooks/pre-commit` → `<内容仓库>/.git/hooks/pre-commit`。**Codex 没有 permissions.deny，禁令①在这边只有 pre-commit 一道**——切换驾驶员时驾驶员必须说出这个差别。
6. `plug check --contact codex` 四步全绿才算接上。

记录的 `by` 字段写「codex · <模型> · <日期>」，同一个处境两个驾驶员的判断可以对照。
