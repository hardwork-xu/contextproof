# ContextProof：跨版本的代码证据

[English](../README.md) · [图接口与契约](GRAPH.md) ·
[模型实验协议](REVISION_STUDY_PROTOCOL.md) · [历史 v1 报告](TECHNICAL_REPORT.md)

代码库修改后，编程助手保存的调用者可能一字未变，但它依赖的函数已经变了。
ContextProof 保存源码及其支持解析的 Python 依赖，指出哪条依赖路径发生变化，
并把当前代码放进有明确字节预算的模型输入。

图工作流包含 Git 不可变版本读取、有限深度的依赖图、精确可重建的差量、
本地保存的证据句柄，以及 CLI 和 MCP 接口。动态调用、外部引用、同名歧义、
缺失源码和预算不足都会显式保留。默认工具只依赖 Python 标准库，支持
Python 3.11+、macOS/Linux；日常使用不需要模型、GPU 或 API Key。

## 运行三跳依赖演示

```sh
git clone https://github.com/hardwork-xu/contextproof.git
cd contextproof
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python scripts/demo_graph.py
```

用浏览器打开 `docs/assets/graph-demo.html`。这是明确标注的合成演示：脚本
创建真实 Git 提交，把第三跳依赖从 `0.05` 改成 `0.20`，调用实际实现，
检查新源码是否进入模型正文、差量能否精确恢复完整图，以及不相关改动、
无法解析的引用和极小预算分别如何处理。示例源码不会被执行。

## 用在自己的仓库中

把下面三个大写占位符替换为真实仓库路径与提交：

```sh
contextproof graph-capture REPOSITORY "invoice_total" \
  --ref BEFORE_COMMIT --budget 16000 \
  --output work/before.json --payload work/before-context.json

contextproof graph-refresh REPOSITORY work/before.json \
  --ref AFTER_COMMIT --view full --budget 16000 \
  --output work/after.json --payload work/current-context.json \
  --delta work/change.json

contextproof graph-apply work/before.json work/change.json \
  --output work/reconstructed.json
```

`--view full` 给出当前源码；`--view update` 用于客户端保留了指定旧图的场景，
不能把增量正文当作独立的完整上下文。**预算统计 `--payload` 文件中的全部
UTF-8 字节**，包含代码、引用和摘要诊断；完整图、CLI 回执、模型会话封装与
工具定义另算。退出码 `1` 表示覆盖不完整，`2` 表示输入或操作错误。

不指定 `--ref` 时会读取并计算工作树文件哈希，但不承诺多个文件的原子快照。
Git 版本读取只使用本地对象，不联网补取缺失对象，也不执行仓库代码。

## 四个需要区分的结果

| 结果 | 实际含义 | 边界 |
|---|---|---|
| 源码指纹相同 | 记录的源码身份与文本相同 | 不证明行为相同，也不是作者签名 |
| 静态依赖未变 | 在声明范围内的定义、导入绑定和路径未变 | unresolved 或达到限制时不能报告新鲜 |
| 模型正文完整 | 所需源码及范围内信息都装入了预算 | 不保证足以完成任务 |
| 差量精确恢复 | 对指定旧图应用差量后，结果与目标图一致 | 文件体积减少不等于模型 token 或费用减少 |

默认扩展深度为 4，最多 256 个节点。完整函数或类放不下时会明确报告省略，
不会从中间截断代码。模型侧诊断使用有计数和截断标记的摘要，完整证据保留
在本地。节点身份与源码指纹分开，因此只移动行号时可以只更新引用位置。

MCP 服务在请求之间复用内存 AST，同时重新检查源码和解析目录。落盘 AST
方案在公平对照中出现额外开销，因此改为显式可选，不宣传未经证实的加速。

## MCP 与旧接口

按 [examples/mcp.json](../examples/mcp.json) 配置固定源码根目录。
`contextproof serve ROOT` 提供 10 个工具；新增的
`contextproof_graph_capture` 保存完整图并返回有预算的源码与句柄，
`contextproof_graph_refresh` 用句柄刷新到当前版本。

原有 `bundle/verify/repair` 仍用于精确片段校验和迁移；v1 的
`capture/check/refresh` 仍保留直接依赖诊断。但旧接口的源码正文不保证包含
发生变化的依赖代码，模型需要这些代码时应使用图工作流。旧实验不会因新接口
上线而被改写成正结果。

## 实验记录

[图重放研究](../benchmarks/graph/README.md)检查重建一致性、传递依赖观察、
正文覆盖与缓存代价。最初诊断元数据挤占代码预算的失败、落盘缓存更慢的
结果，以及词法作用域审查发现的错误，都保留为带版本的记录。

[真实版本行为研究](REVISION_STUDY_PROTOCOL.md)使用四个开源库的 30 个
上游回归测试衍生任务，其中 5 个开发任务、25 个留出任务。所有方法共享
源码定位提示和 16,000 字节证据预算，对照包括无源码、旧源码、新源码、
BM25、传递图和真实运行的 Archex 0.31.2。最终运行配置先通过了 5/5 开发
任务能力检查，再开始留出实验；协议与输入已提前提交到公开仓库。
这是带源码提示的 API 输出预测，不是完整软件问题修复或通用 agent 排名。

历史材料继续保留：[300 条精确文本漂移样本](DRIFT_STUDY.md)、
[34 项直接依赖控制案例](DEPENDENCIES.md)，以及
[三组均为 0/20 的 60 次 Qwen 生成](DOWNSTREAM.md)。同一改动族中的多个
任务存在相关性；测试数量、源码校验一致性和差量体积不能替代模型效果证据。

## 复现与发布

```sh
python -m pip install -e '.[dev]'
ruff check .
pytest -q
python scripts/check_publication.py
python -m build
```

安装 `.[integration]` 后可运行 `python scripts/check_mcp_sdk.py`，通过官方
MCP SDK 验证实际 stdio 调用。模型推理不在 CI 中自动运行。

公开仓库保留技术实现、实验输入、脱敏后的答案、失败记录和原始/公开文件哈希。
个人规划、账号信息、原始本机日志与完整备份保存在 Git 仓库之外。
[发布政策](PUBLISHING.md)说明脱敏规则；脱敏不会改变实验分数或隐藏失败。

项目由 **hardwork-xu** 维护，使用 AI 辅助设计、实现、实验与写作。
采用 [MIT 许可证](../LICENSE)，上游来源与许可证保留在各实验 manifest 中。
