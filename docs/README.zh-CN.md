# ContextProof：代码改了，AI 之前读到的证据还能用吗？

[English](../README.md) · [公开仓库](https://github.com/hardwork-xu/contextproof) ·
[真实实验结果](../benchmarks/results/latest.md) · [评估协议](EVALUATION.md)

ContextProof 是一个给 AI 编程助手使用的本地代码证据工具。它先检索代码，
保存片段、路径、行号、哈希和来源；代码库变化后，再检查旧证据是否仍然精确
匹配。插入几行或移动文件时，可以修正唯一匹配的引用；片段被修改、删除或
出现多个候选位置时，会明确报告失效或歧义。

当前是 **v0.1 可运行研究原型**：包含 CLI、MCP stdio 接口、自动化测试和
可复现实验。使用 Python 3.11+，面向 macOS/Linux；默认安装没有运行时依赖，
不需要 GPU、模型 API 或付费服务。

## 一个具体例子

AI 保存了 `pricing.py` 的第 4–8 行。你随后在文件顶部加了一行注释。
原来的代码还在，但引用行号已经错了。

- 只检查原来的行号，会认为证据已经变化。
- 只比较整个文件的哈希，也只能知道文件变了。
- ContextProof 查找原片段的精确文本；只有一个匹配位置时，更新引用行号，
  再验证修复后的证据。

这里验证的是**文本是否仍然一致**。如果片段调用的另一个函数变了，即使
片段本身没变，程序行为仍可能变化。当前版本不会把“文本相同”说成“行为相同”。

## 三分钟跑起来

从 GitHub 安装；当前没有发布到 PyPI。在项目根目录执行：

```sh
git clone https://github.com/hardwork-xu/contextproof.git
cd contextproof
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .

contextproof index examples/tinyshop
contextproof bundle examples/tinyshop "discount price rate" \
  --method bm25 --budget 4000 --output work/demo.json
contextproof verify examples/tinyshop work/demo.json
contextproof render work/demo.json --output work/demo.md
```

`work/demo.json` 保存可验证的证据，`work/demo.md` 是交给 AI 的正文。
这里的预算是 **4,000 个 UTF-8 字节**，不是 4,000 个模型 token。

接着在临时副本中插入一行，观察引用修复：

```sh
python - <<'PY'
from pathlib import Path
from shutil import copytree

source = Path("examples/tinyshop")
changed = Path("work/tinyshop")
copytree(source, changed, dirs_exist_ok=True)
(changed / "pricing.py").write_bytes(
    b"# Header added after retrieval.\n" + (source / "pricing.py").read_bytes()
)
PY

# 此处出现 relocated、退出码为 1 是预期结果。
contextproof verify work/tinyshop work/demo.json
contextproof repair work/tinyshop work/demo.json --output work/repaired.json
contextproof verify work/tinyshop work/repaired.json
contextproof render work/repaired.json --output work/repaired.md
```

修复后的引用应当恢复为 `valid`。如果直接改变片段中的表达式，系统会将它
标为失效，而不会偷偷用新代码替换旧证据；这时需要重新检索。
生成文件均位于被索引示例之外，避免把自己的输出当成新的源码。

## 项目中值得理解的技术

| 部分 | 做了什么 | 需要能解释的问题 |
| --- | --- | --- |
| AST 切块 | 按 Python 类、函数和源代码范围组织片段 | 装饰器、嵌套函数与长函数如何定位？ |
| 检索 | BM25 与简单依赖图扩展 | 图扩展为什么也可能降低效果？ |
| SQLite 缓存 | 复用内容未变的解析结果 | 为什么缓存命中仍需要读取文件？ |
| 预算打包 | 计入完整正文和引用元数据，放不下就跳过整个片段 | 如何保证统计范围与实际发送内容一致？ |
| 跨版本验证 | 区分有效、迁移、修改、删除、歧义、无效输入 | 精确匹配能证明什么、不能证明什么？ |
| 可复现实验 | 固定源码版本、采样规则、对照方法与结果文件 | 真实版本变化为什么不能直接当准确率？ |

完整实现说明见[系统设计](DESIGN.md)。预算约束覆盖渲染后的正文，包含查询、
引用、代码和来源信息；JSON 存储记录、MCP 外层封装、其他对话消息及模型接口
开销不在预算内。可选安装 `.[tokens]` 后使用 `cl100k_base` 或 `o200k_base`；
首次使用可能下载编码表，编码计数也不等于完整请求的计费 token。

## 已经测到什么

- 7 种受控变化均得到预期验证状态，修复结果也符合契约。
- 在 Click、ItsDangerous、MarkupSafe 的两个冻结版本之间检查了 118 个片段。
  这些是状态分布，尚无独立标注，不能说是 118 个样本的准确率。
- 14 个手写检索问题，分别使用 2 种方法和 3 档预算，共 84 次运行，
  完整渲染预算均未超限。
- 2,000 字节时，图扩展命中相关文件的问题数为 8/14，低于 BM25 的 9/14；
  4,000 字节时两者相同，8,000 字节时分别为 14/14 和 13/14。

这些问题经常包含精确函数名，三个仓库也来自同一 Pallets 生态，因此结果
不能证明图方法普遍更强。当前没有运行下游 LLM 编程任务，没有论文录用或
模型成功率提升的结论。负面结果也保留在[实验报告](../benchmarks/results/latest.md)。

复现实验：

```sh
python scripts/run_benchmarks.py --download
python scripts/run_benchmarks.py \
  --check benchmarks/results/latest.json --output work/repeated-results
```

脚本校验冻结归档的 SHA-256，只读取上游源码，不安装或执行上游项目。
第二条命令比较确定性结果；时间、机器环境和耗时单独记录。
详见[实验协议](EVALUATION.md)。

## 如何把它继续做扎实

[研究定位](RESEARCH.md)说明已有工作与可证伪问题；
[路线图](ROADMAP.md)列出下一阶段实验的验收标准。

项目由 **hardwork-xu 维护，使用 AI 辅助设计、实现与文档**。
开发记录如实记录本次实际产出，不虚构团队、数月开发经历或尚未完成的研究。
默认采用 [MIT 许可证](../LICENSE)；实验使用的公开源码来源及其许可证记录在
[manifest](../benchmarks/manifest.json)中。
