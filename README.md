# Chat to Note · 对话转结构化笔记 Skill

> 把 Claude Code / Codex 的高质量对话整理成结构化知识笔记——读 transcript 抗 compaction、按对话类型选结构、去试错过程、留决策链与推理、底部折叠原文。works in both **Claude Code** and **Codex**。

## ✨ 特性

- 🧠 **读 transcript，不靠回忆**：用可核验的会话 ID 或指定路径定位 transcript（抗 compaction），从 jsonl 提取可读对话
- 🧩 **按对话类型选结构**：自动判断技术决策 / 知识问答 / 调试排错 / 头脑风暴 / 代码实现五型，匹配不同结构
- ✂️ **精准删留**：删寒暄 / 格式确认 / 失败尝试 / 工具过程，留结论 / 推理链 / 决策依据 / 代码方案
- 📎 **折叠原文**：底部折叠保留清洗后对话原文，超 200 轮自动精简并标注 transcript 路径
- 🔌 **两端通用**：Claude Code 和 Codex 的 transcript 格式都能解析，自动识别当前运行时

## 📦 安装

**Claude Code：**
```bash
git clone https://github.com/pamler1004/chat-to-note.git ~/.claude/skills/chat-to-note
```

**Codex：**
```bash
git clone https://github.com/pamler1004/chat-to-note.git ~/.codex/skills/chat-to-note
```

纯文本 skill，依赖 Python 3（仅用于 transcript 解析脚本，标准库无第三方依赖）。clone 完在对话里说「整理这次对话」「把会话存成笔记」即可触发。

## 🎯 用法

在 Claude Code 或 Codex 里结束一次高质量对话后，说「整理这次对话」。它会：

1. 使用可核验的会话 ID 或指定路径定位 transcript；身份不明时不按最近修改时间猜测
2. Python 脚本解析 jsonl，过滤 thinking / tool_use / reasoning 等过程噪声
3. 判断对话类型，按匹配结构建立大纲
4. 按价值点（非时间线）提炼：结论、推理链、决策依据、代码方案
5. 底部折叠保留清洗后原文（超 200 轮精简）
6. 归档到 Obsidian vault（目录由 `vault-path.local` 配置，首次使用时询问并记住）

### 核心机制：为什么读 transcript

compaction（上下文压缩）后，模型只剩 summary，原始细节会丢。但 transcript 文件不受 compaction 影响，完整保留所有原始消息。本 skill 以 transcript 文件为真相来源，天然抗 compaction——比「让模型回忆」可靠得多。

### 对话类型自动判断

| 类型 | 结构 |
|---|---|
| 技术决策 | 背景 → 方案 → 取舍 → 结论 |
| 知识问答 | Q&A 精炼 |
| 调试排错 | 问题 → 原因 → 解法 |
| 头脑风暴 | 想法清单 + 决策 |
| 代码实现 | 需求 → 要点 → 代码 |

高置信（≥70%）直接生成，低置信才一句话请求确认。完成后附「如不合适可让我用 X/Y 型重整」。

## 🔗 同族 skill

- [zimu-to-note](https://github.com/pamler1004/zimu-to-note)：字幕/逐字稿 → 笔记（单向线性内容，去口播味，按主题重组）

本 skill 是对话场景的对应：去试错过程，按价值点重组，保护问答感与决策链。

## 📄 License

MIT
