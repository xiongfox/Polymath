#!/usr/bin/env python3
"""博物馆 AI 讲解 Agent 命令行入口（多轮对话）。"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage

from agent.graph import create_agent

load_dotenv()


def main() -> None:
    parser = argparse.ArgumentParser(description="博物馆 AI 讲解 Agent")
    parser.add_argument(
        "--wiki-root",
        type=Path,
        default=None,
        help="Wiki 根目录，默认项目 wiki/",
    )
    parser.add_argument(
        "--thread",
        type=str,
        default=None,
        help="会话线程 ID，用于恢复多轮上下文",
    )
    parser.add_argument(
        "--show-meta",
        action="store_true",
        help="保留回答末尾的意图/Wiki 元信息（默认隐藏）",
    )
    parser.add_argument(
        "--no-llm-intent",
        action="store_true",
        help="仅使用规则进行意图识别（不调用 LLM 补全）",
    )
    args = parser.parse_args()

    if args.no_llm_intent:
        os.environ["MUSEUM_AGENT_NO_LLM_INTENT"] = "1"

    agent = create_agent(wiki_root=args.wiki_root)
    thread_id = args.thread or str(uuid.uuid4())[:8]
    config = {"configurable": {"thread_id": thread_id}}

    print("博物馆 AI 讲解助手")
    print(f"会话 ID: {thread_id}（退出请输入 quit）")
    print("提示：可先问「介绍一下南京博物院」，再问「蝙蝠虫在哪个展厅」体验多轮指代。\n")

    while True:
        try:
            user_input = input("您: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见。")
            break

        if not user_input:
            continue
        if user_input.lower() in {"quit", "exit", "q", "退出", "再见"}:
            print("再见。")
            break

        state_in = {
            "messages": [HumanMessage(content=user_input)],
            "user_query": user_input,
        }
        try:
            result = agent.invoke(state_in, config=config)
        except Exception as exc:
            print(f"\n[错误] {exc}")
            print("请确认 Ollama 已启动且已拉取模型，例如: ollama pull qwen3:8b\n")
            continue

        reply = _extract_reply(result)
        if not args.show_meta:
            reply = _strip_meta(reply)
        print(f"\n讲解员: {reply}\n")


def _extract_reply(result: dict) -> str:
    messages = result.get("messages") or []
    for m in reversed(messages):
        if isinstance(m, AIMessage):
            return m.content if isinstance(m.content, str) else str(m.content)
        if isinstance(m, dict) and m.get("role") == "assistant":
            return m.get("content", "")
    return "（无回复）"


def _strip_meta(text: str) -> str:
    lines = text.split("\n")
    while lines and lines[-1].strip().startswith("〔"):
        lines.pop()
    return "\n".join(lines).rstrip()


if __name__ == "__main__":
    main()
