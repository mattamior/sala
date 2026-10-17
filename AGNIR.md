# Agnir Project Instructions — sala

本文件是 sala 的 Agnir 执行者入口。Agnir 用于保存**项目拥有的、可跨会话恢复的事实**，不是 Agent 运行时或应用程序依赖。

## Activation / 激活

1. 只从授权的项目入口 `mattamior/sala`（及用户明确指定的 ref）开始，先读根目录 `AGENTS.md`，随后阅读本文件；不要猜测其他仓库或相邻目录。
2. 读取根目录 `AGNIR.yaml`，严格验证 `agnir.version`、`agnir.discovery_profile`、`project.identity`、所选 `continuity.lineage`。若使用 VCS 选择器，再单独验证 selector/binding，不要把分支名或提交 SHA 当作 lineage identity。
3. 从 manifest 声明的位置加载 **Current State** 与 **Next Actions**，并在相关时加载 **Decisions**、**Evidence**。新近的用户明确指令和直接项目观测可覆盖较旧的持久记录；不要依赖上一位 Agent 的私有聊天上下文。
4. 再执行真正的项目任务。产品事实及设计讨论可参见 `docs/`；若其与 Agnir 状态冲突，先核实时间与来源，必要时调和并更新。

## Checkpoint / 检查点

在保存、结束、提交或推送边界：

1. 按真实项目变化调和状态、行动、决定和证据；不要把对话逐字转存为“项目事实”。
2. 没有实质变化时，checkpoint 检查为 **no-op**，不制造无意义的 `.agnir/` 改动。
3. 有实质变化时，在发布前构建一致的候选状态；检测基线是否已变化，拒绝过期覆盖，报告 `AGNIR_CHECKPOINT_CONFLICT` 并重新核对。
4. 尽量把项目变动和必要的连续性更新包含在一个一致的 Git 修订里；发布后重新按 manifest 检查同一 Project identity 与 lineage 能被读取。

## Repository operations / 仓库操作

- 在仓库上下文中，“commit / 提交 / 提交代码”意味着：**checkpoint 检查 → 已声明的预提交策略（若有）→ commit**。
- “commit and push / 提交推送”意味着：**checkpoint 检查 → 预提交策略（若有）→ commit → push → 验证目标 ref**。
- 不要通过孤立的提交路径绕过 checkpoint 评估。不要将一个分支的连续性内容未经调和直接覆盖另一个 lineage。
- 在没有另行批准的情况下，不要把概念设计、技术选型候选或预演研究写成“已经实现/已经选定”。

## Compatibility

- 当前 Project 使用 Agnir Core `1.0` / `repository-filesystem/1.0`；以 `AGNIR.yaml` 为真实声明，不做静默迁移。
- 初始化依照 `iorLab/agnir` 的稳定发行包 `v1.0.2`、根目录 `SKILL.md`，来源修订记录在 manifest 的 `agnir/operations`。
- `README.md#Agnir-Project-Instructions` 是兼容旧入口的指针，只指向本文件，不能维护第二份操作规范。
