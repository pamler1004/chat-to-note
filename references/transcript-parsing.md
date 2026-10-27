# Transcript 解析规范

`scripts/extract_transcript.py` 的设计依据与维护参考。记录 Claude / Codex 两端 transcript 的结构与解析规则。

## 为什么用脚本而非模型直读

jsonl 动辄 1.7MB、结构嵌套深，模型直接读会爆 context 且易错。脚本做清洗过滤，只输出 user/assistant 的文本内容，去掉过程噪声，供模型基于「可读对话文本」整理。

## Claude transcript

### 位置
`~/.claude/projects/<工作目录转义>/<session-id>.jsonl`

工作目录转义规则：`/` -> `-`，非 ASCII 字符 -> `-`。脚本不根据工作目录猜当前会话；优先使用精确 session ID，否则由用户通过路径显式指定。

### 消息结构
每行一个 JSON 对象。相关字段：
- `type`: `user` / `assistant` / `queue-operation` / `attachment` / `system` 等
- `message`: `{role, content, ...}`
  - `content` 可能是 `str`（纯文本 user）或 `list`（含多个 block）
  - block 类型：`text`（保留）/ `thinking`（丢弃）/ `tool_use`（丢弃）/ `tool_result`（丢弃）
- 过滤标记：`isCompactSummary`（compaction 摘要）/ `isMeta`（元消息）/ `isSidechain`（子代理）

### 解析规则
1. 取 `type in (user, assistant)`
2. 过滤 `isCompactSummary / isMeta / isSidechain`
3. `content` 为 str：直接取
4. `content` 为 list：只取 `block.type == 'text'` 的 text，丢弃 thinking / tool_use / tool_result
5. 拼接为 (role, text) 轮次

### 为什么丢弃 thinking / tool_use
- `thinking`：assistant 内部推理，太长且结论已体现在 text 输出
- `tool_use` / `tool_result`：工具调用过程（Read/Bash/Edit），结论已体现在后续 assistant text 里。保留它们会注入大量文件内容噪声

## Codex transcript

### 位置
- 活跃：`~/.codex/sessions/YYYY/MM/rollout-*.jsonl`
- 归档：`~/.codex/archived_sessions/rollout-*.jsonl`
- 索引：`~/.codex/session_index.jsonl`（含 id / thread_name / updated_at）

### 消息结构
每行一个 JSON 对象：`{type, timestamp, payload}`。`type` 含 `response_item` / `event_msg` / `session_meta` 等。

`response_item.payload` 的 type：
- `message`（保留）：`{role, content, ...}`，role 含 `user` / `assistant` / `developer`
  - `content` 是 `list[{type, text}]`，提取 text
- `reasoning`（丢弃）：加密的推理内容，拿不到明文
- `custom_tool_call`（丢弃）：工具调用
- `custom_tool_call_output`（丢弃）：工具返回

### 解析规则
1. 取 `type == 'response_item'` 且 `payload.type == 'message'`
2. `role in (user, assistant)`，丢弃 `developer`（系统提示）
3. 过滤 Codex 系统注入的 user 消息（见下方「系统注入过滤」）
4. 提取 `content` 各 block 的 text
5. 拼接为 (role, text) 轮次

### 系统注入过滤

Codex 运行时会往 user role 塞入大量上下文块，**不是用户真实输入**，整条过滤（按 `text.lstrip()` 前缀匹配）：

| 前缀 | 含义 | 237 会话统计 |
|------|------|-------------|
| `<recommended_plugins>` | 可用插件推荐 | 195 次 |
| `<environment_context>` | cwd/shell/系统环境 | 105 次 |
| `<in-app-browser-context` | 浏览器内嵌状态 | 68 次 |
| `<skill>` | 已激活 skill 元信息 | 29 次 |
| `<subagent_notification>` | 子代理状态通知 | 21 次 |
| `<turn_aborted>` | 用户中断上一轮 | 20 次 |
| `<heartbeat>` | 心跳 | 2 次 |
| `<codex_delegation>` | 委派上下文 | 2 次 |

这些约占 user 消息的 24%，不过滤会严重污染笔记原文（plugin 列表尤其长且无信息量）。

**不过滤** `<image ...>`：那是用户贴图，是真实输入。新增注入类型时，在脚本的 `_CODEX_SYS_PREFIXES` 元组补充。

## 自动定位策略

脚本不指定 `--path` 时，只在 session ID 精确匹配唯一 transcript 时自动定位：Claude 使用 `CLAUDE_CODE_SESSION_ID` 精确匹配文件名；Codex 使用 `CODEX_SESSION_ID` / `CODEX_ROLLOUT_ID`，匹配完整文件 basename 或完整 UUID 对应的 `rollout-YYYY-MM-DDTHH-MM-SS-<uuid>.jsonl` 等文件，并同时检查活跃与 archived transcript。短 ID、部分 UUID 和 glob 元字符不参与匹配；多个文件匹配即视为歧义并停止。`--session-id <id>` 显式按相同规则匹配，`--tool claude|codex` 可限定来源。环境变量只表示运行时线索，不能证明会话身份；mtime 仅是候选排序信息，绝不用于自动选中。

### 已知边界
- Claude ID 若匹配多个 project 文件，或 Codex ID 匹配多个活跃/归档文件，必须用 `--path` 显式选定；不能以 `PREVIEW` 代替会话身份核验
- Codex `developer` role 是系统提示，含大量 plugin 列表等噪声，已过滤
- Codex user role 里有系统注入块（`<recommended_plugins>` 等），已用前缀白名单过滤，见上方「系统注入过滤」

## 输出

- **stdout**：临时文件路径（Markdown，含来源/轮次/逐条对话）
- **stderr**：`TOOL` / `PATH` / `TURNS` / `PREVIEW`，>200 轮时附 `TRUNCATE_SUGGESTED`

## 维护提示

- transcript 格式可能随 Claude Code / Codex 升级变化。若解析结果异常（轮次为 0 或内容缺失），先用 `head -1 <jsonl> | python3 -m json.tool` 看结构是否变了
- 新增过滤字段时，在 `parse_claude` / `parse_codex` 里加判断，保持「只输出文本结论」的原则
