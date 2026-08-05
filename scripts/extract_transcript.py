#!/usr/bin/env python3
"""extract_transcript.py — 从 Claude Code / Codex 的 transcript jsonl 提取可读对话文本。

用法:
  python3 extract_transcript.py                  # 自动定位当前会话（mtime 最新）
  python3 extract_transcript.py --path <file>    # 指定 transcript 文件
  python3 extract_transcript.py --tool claude    # 强制按 Claude 解析
  python3 extract_transcript.py --tool codex     # 强制按 Codex 解析

输出:
  stdout — 临时文件路径（内含清洗后的可读对话 Markdown）
  stderr — 元信息：TOOL / PATH / TURNS / PREVIEW，>200 轮时附 TRUNCATE_SUGGESTED

设计理由：jsonl 动辄 1.7MB，让模型直接读会爆 context 且易错。本脚本做清洗过滤，
只输出 user/assistant 的文本内容，去掉 thinking / tool_use / tool_result / reasoning
等过程噪声，供模型基于「可读对话文本」做整理。
"""

import argparse
import glob
import json
import os
import sys
import tempfile

# Codex 系统注入的 user 消息前缀（纯噪声，整条过滤）。
# 这些是 Codex 运行时塞进 user role 的上下文，不是用户真实输入：
#   <recommended_plugins>  可用插件推荐（最常见）
#   <environment_context>  cwd/shell/系统环境
#   <in-app-browser-context  浏览器内嵌状态
#   <skill>                 已激活 skill 元信息
#   <subagent_notification> 子代理状态通知
#   <turn_aborted>          用户中断上一轮
#   <heartbeat>             心跳
#   <codex_delegation>      委派上下文
# 注意：<image ...> 是用户贴图，是真实输入，不在过滤列表。
_CODEX_SYS_PREFIXES = (
    "<recommended_plugins>",
    "<environment_context>",
    "<in-app-browser-context",
    "<skill>",
    "<subagent_notification>",
    "<turn_aborted>",
    "<heartbeat>",
    "<codex_delegation>",
)


def find_latest_claude():
    """~/.claude/projects/**/*.jsonl 中 mtime 最新的"""
    base = os.path.expanduser("~/.claude/projects")
    files = glob.glob(os.path.join(base, "*", "*.jsonl"))
    return max(files, key=os.path.getmtime) if files else None


def find_latest_codex():
    """~/.codex/sessions/**/*.jsonl 中 mtime 最新的"""
    base = os.path.expanduser("~/.codex/sessions")
    files = glob.glob(os.path.join(base, "**", "*.jsonl"), recursive=True)
    if not files:
        files = glob.glob(os.path.expanduser("~/.codex/archived_sessions/*.jsonl"))
    return max(files, key=os.path.getmtime) if files else None


def detect_current_tool():
    """通过环境变量判断当前运行时。

    Claude Code 设 CLAUDECODE=1 / CLAUDE_CODE_SESSION_ID；
    Codex 设 CODEX_* 环境变量。用于精确定位「当前」会话，避免 mtime 误命中另一工具的会话。
    """
    if os.environ.get("CLAUDECODE") == "1" or os.environ.get("CLAUDE_CODE_SESSION_ID"):
        return "claude"
    if any(k.startswith("CODEX") for k in os.environ):
        return "codex"
    return None


def find_current_session():
    """优先用环境变量精确定位当前会话，返回 (path, tool) 或 None。

    Claude: 用 CLAUDE_CODE_SESSION_ID 直接定位文件名，无需猜 project 目录转义。
    Codex:  退回 mtime 最新（Codex 未暴露 session-id 环境变量）。
    """
    tool = detect_current_tool()
    if tool == "claude":
        sid = os.environ.get("CLAUDE_CODE_SESSION_ID")
        if sid:
            files = glob.glob(os.path.expanduser(f"~/.claude/projects/*/{sid}.jsonl"))
            if files:
                return files[0], "claude"
        c = find_latest_claude()
        if c:
            return c, "claude"
    elif tool == "codex":
        x = find_latest_codex()
        if x:
            return x, "codex"
    return None


def detect_tool(path):
    p = path.lower()
    if ".codex" in p or os.path.basename(p).startswith("rollout"):
        return "codex"
    return "claude"


def parse_claude(path):
    """解析 Claude transcript jsonl -> [(role, text)]

    过滤 isCompactSummary / isMeta / isSidechain；保留 user 文本 + assistant 的 text 块；
    丢弃 thinking / tool_use / tool_result（工具过程，结论已体现在 assistant text 里）。
    """
    turns = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if d.get("type") not in ("user", "assistant"):
                continue
            if d.get("isCompactSummary") or d.get("isMeta") or d.get("isSidechain"):
                continue
            msg = d.get("message", {})
            role = msg.get("role", d["type"])
            content = msg.get("content")
            texts = []
            if isinstance(content, str):
                texts.append(content)
            elif isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "text":
                        texts.append(block.get("text", ""))
                    # thinking / tool_use / tool_result 一律丢弃
            text = "\n".join(t for t in texts if t and t.strip())
            if text.strip():
                turns.append((role, text))
    return turns


def parse_codex(path):
    """解析 Codex rollout jsonl -> [(role, text)]

    取 response_item.payload.type=message 且 role in (user, assistant)；
    丢弃 developer（系统提示）、reasoning（加密）、custom_tool_call（工具过程）。
    Codex 会把 plugin 推荐/环境上下文等塞进 user role，用 _CODEX_SYS_PREFIXES 过滤。
    """
    turns = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if d.get("type") != "response_item":
                continue
            p = d.get("payload", {})
            if p.get("type") != "message":
                continue
            role = p.get("role", "?")
            if role not in ("user", "assistant"):
                continue
            content = p.get("content", [])
            texts = []
            if isinstance(content, str):
                texts.append(content)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        texts.append(block.get("text", ""))
            text = "\n".join(t for t in texts if t and t.strip())
            if not text.strip():
                continue
            # 过滤 Codex 系统注入的 user 消息（plugin 推荐/环境上下文/浏览器状态等，非用户真实输入）
            if role == "user" and text.lstrip().startswith(_CODEX_SYS_PREFIXES):
                continue
            turns.append((role, text))
    return turns


def format_turns(turns, source_path, tool):
    lines = [
        f"# 对话原文（自动提取自 {tool} transcript）",
        f"- 来源: `{source_path}`",
        f"- 有效消息数: {len(turns)}",
        "",
    ]
    for i, (role, text) in enumerate(turns, 1):
        icon = "👤" if role == "user" else "🤖"
        lines.append(f"## {icon} {role} #{i}")
        lines.append("")
        lines.append(text)
        lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="提取 Claude/Codex transcript 为可读对话文本")
    ap.add_argument("--path", help="指定 transcript 文件")
    ap.add_argument("--tool", choices=["claude", "codex"], help="强制工具类型")
    args = ap.parse_args()

    if args.path:
        path = os.path.expanduser(args.path)
        tool = args.tool or detect_tool(path)
    else:
        # 优先用环境变量定位当前会话
        cur = find_current_session()
        if args.tool == "claude":
            if cur and cur[1] == "claude":
                path, tool = cur
            else:
                c = find_latest_claude()
                if not c:
                    print("ERROR: 找不到 Claude transcript", file=sys.stderr)
                    sys.exit(1)
                path, tool = c, "claude"
        elif args.tool == "codex":
            if cur and cur[1] == "codex":
                path, tool = cur
            else:
                x = find_latest_codex()
                if not x:
                    print("ERROR: 找不到 Codex transcript", file=sys.stderr)
                    sys.exit(1)
                path, tool = x, "codex"
        elif cur:
            path, tool = cur
        else:
            # fallback: 无环境变量线索时取两边 mtime 最新
            c = find_latest_claude()
            x = find_latest_codex()
            if c and x:
                if os.path.getmtime(c) >= os.path.getmtime(x):
                    path, tool = c, "claude"
                else:
                    path, tool = x, "codex"
            elif c:
                path, tool = c, "claude"
            elif x:
                path, tool = x, "codex"
            else:
                print("ERROR: 找不到任何 transcript 文件", file=sys.stderr)
                sys.exit(1)

    if not os.path.exists(path):
        print(f"ERROR: 文件不存在: {path}", file=sys.stderr)
        sys.exit(1)

    turns = parse_claude(path) if tool == "claude" else parse_codex(path)

    if not turns:
        print(f"ERROR: 未提取到任何对话内容: {path}", file=sys.stderr)
        sys.exit(1)

    out = format_turns(turns, path, tool)
    fd, tmp = tempfile.mkstemp(suffix=".md", prefix="transcript_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(out)

    # 元信息到 stderr
    print(f"TOOL: {tool}", file=sys.stderr)
    print(f"PATH: {path}", file=sys.stderr)
    print(f"TURNS: {len(turns)}", file=sys.stderr)
    if len(turns) > 200:
        print(f"TRUNCATE_SUGGESTED: {len(turns)} 轮 > 200，建议底部原文精简", file=sys.stderr)
    first_user = next((t for r, t in turns if r == "user"), "")
    print(f"PREVIEW: {first_user.replace(chr(10), ' ')[:80]}", file=sys.stderr)
    # stdout 只输出文件路径，方便 SKILL 捕获
    print(tmp)


if __name__ == "__main__":
    main()
