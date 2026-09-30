"""Agent 组件工厂（供 API 调用，不改变 LangGraph CLI 流程）。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from langchain_ollama import ChatOllama

from agent.intent import IntentRecognizer
from agent.wiki_index import WikiIndex

DEFAULT_WIKI_ROOT = Path(__file__).resolve().parent.parent / "wiki"


@dataclass
class AgentBundle:
    wiki_root: Path
    wiki_index: WikiIndex
    intent_recognizer: IntentRecognizer
    chat_llm: ChatOllama


_bundle: AgentBundle | None = None


def create_agent_bundle(
    wiki_root: Path | str | None = None,
    *,
    model: str | None = None,
    base_url: str | None = None,
    force_reload: bool = False,
) -> AgentBundle:
    global _bundle
    if _bundle is not None and not force_reload:
        return _bundle

    wiki_path = Path(wiki_root or os.getenv("WIKI_ROOT", DEFAULT_WIKI_ROOT))
    model_name = model or os.getenv("OLLAMA_MODEL", "qwen3:8b")
    ollama_base = base_url or os.getenv("OLLAMA_BASE_URL")

    wiki_index = WikiIndex.build(wiki_path)
    intent_recognizer = IntentRecognizer(
        wiki_index, model=model_name, base_url=ollama_base
    )
    chat_llm = ChatOllama(model=model_name, base_url=ollama_base, temperature=0.3)

    _bundle = AgentBundle(
        wiki_root=wiki_path,
        wiki_index=wiki_index,
        intent_recognizer=intent_recognizer,
        chat_llm=chat_llm,
    )
    return _bundle


def invalidate_agent_bundle() -> None:
    global _bundle
    _bundle = None
