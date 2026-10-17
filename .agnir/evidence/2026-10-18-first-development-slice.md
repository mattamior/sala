# sala first executable slice — 2026-10-18

## User intent and scope

- 新用户指令：「对，我们已经讨论了很多内容，应该尽快把讨论收尾，进行开发。」
- 意图是从产品/架构研讨转入代码开发，而不是把之前的所有草案一次性批准为最终技术架构。
- 选择最小可运行的**工程验证切片**；原型路径：`src/sala/`、`tests/`、`DEV.md` 和 `.github/workflows/test.yml`。

## Verified execution

- Python 3.13.5（开发容器）+ FFmpeg / ffprobe 的实际本地执行测试：`PYTHONPATH=src python -m unittest discover -s tests -v` → **Ran 10 tests ... OK**。
- 真实命令行手动验证：`init` → `run --dry-run` → 截取 1–3 秒 → 提取第 1 秒画面 → `status`，输出视频/图片存在且 revision/history 持久化。
- 「人物转身更快，其他镜头保持不变」因明确保留约束被阻止，退出码 `2`，未产生修改后的工程状态。
- 模拟的 OpenAI-compatible LLM 连接仅用于验证响应结构与动作白名单；**未调用真实远端模型，也未验证 LLM 质量**。

## Limitations

- 截取/提帧是**真实本地媒体操作**，不是生成式创作能力。
- 规划入口目前只能提出受控的单步动作，不能把复杂视频改动能力冒充已实现。
- FFmpeg 验证针对输出文件与近似时长，不提供镜头连续性、身份/动作保留或审美保证。
- 并发修改仅有简易基线比较，没有跨进程排它锁；不要在同一 project 目录并发运行多个进程。
- GitHub Actions 工作流已纳入候选提交；远端工作流运行状态应在提交后单独核实。

## Checkpoint

- Agnir 项目和逻辑 lineage 身份保持不变，权威 ref 仍为 `refs/heads/main`；本次将可运行代码、说明与连续性更新发布为一个 Git 修订。
