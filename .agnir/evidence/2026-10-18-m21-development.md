# M2.1 bounded multi-turn agent loop — 2026-10-18

## Authorization and scope
- 维护者明确请求：「开始 M2.1」。
- 基线：`mattamior/sala` `main` @ `3eb32423a9542eaaf2d19b72b92db8e6dfccb2f0`。
- 原有 `AGENTS.md → AGNIR.md → AGNIR.yaml` 已验证。Agnir Core `1.0`、profile `repository-filesystem/1.0`、Project identity `urn:github:mattamior:sala`、lineage `urn:agnir:sala:initial`、main selector/binding 均保持。
- 新增 `src/sala/session.py`、`tests/test_session.py`；更新 `src/sala/cli.py`、`README.md`、`DEV.md`、Agnir 当前状态与下一步。

## Locally executed verification
- 在本地 Python 3.13 + FFmpeg 环境对 M2.1 工程原型运行 `PYTHONPATH=src python -m unittest discover -s tests -v`：**16 项 M2.1 测试通过**，含实际合成视频裁剪与提帧。
- 测试：两轮「截取→刚才那段提帧」引用、澄清跨命令恢复、当前视频变更后的澄清失效、原始 `run` 兼容、dry-run 无副作用、拒绝范围越界和无法满足的局部保留请求、受限模拟 LLM 规划与未知工具阻止、无动词时不自行执行、CLI 操作。
- 本地验证时使用了与仓库现有 `core.py` API 等价的本地依赖副本；此前基线原有 10 个测试已在 GitHub Actions 通过。本次**全部测试的仓库真实 CI**应以新提交触发后的结果为准，不要提前宣称成功。

## Limitations
- 有限多轮会话，不是通用 autonomous Agent 或多工具生成链。
- 严格保留仅能识别部分显式措辞并拒绝不支持的行为，不提供严格局部视频保真保证。
- 当前的模型端点未做真实连通性测试；mock LLM 仅检验输出约束。
- 现有项目状态采用检查-替换而非完整跨进程锁，不支持并发写入。
- 没有生成式图像/视频后端、主观质量评估或可交付桌面应用。
