"""FastAPI 请求 / 响应模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)


class ChatRequest(BaseModel):
    museum_name: str = Field(..., description="博物馆名称，如：南京博物院")
    question: str = Field(..., description="用户当前问题")
    history: list[ChatMessage] = Field(
        default_factory=list,
        description="历史问答（不含本轮 question），用于多轮意图识别与讲解上下文",
    )
    stream: bool = Field(default=True, description="是否流式返回（text/plain）")


class ChatResponse(BaseModel):
    message: str = Field(description="助手回复正文")


class WikiBuildResponse(BaseModel):
    success: bool
    message: str
    museum_name: str
    total_rows: int
    relic_md_count: int
    hall_md_count: int
    paths: dict[str, str]
    failed_relics: list[str] = Field(default_factory=list)
    failed_halls: list[str] = Field(default_factory=list)
