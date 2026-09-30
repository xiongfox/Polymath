"""
博物馆 AI 讲解 FastAPI 服务。

启动:
  uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from agent.bundle import create_agent_bundle
from api.chat_service import chat, chat_stream
from api.schemas import ChatRequest, ChatResponse, WikiBuildResponse
from api.wiki_build import build_wiki_from_upload

load_dotenv()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    create_agent_bundle()
    yield


app = FastAPI(
    title="博物馆 AI 讲解 API",
    description="Excel 构建 Wiki + 流式对话",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post(
    "/api/v1/wiki/build",
    response_model=WikiBuildResponse,
    summary="上传 Excel 构建博物馆 Wiki",
)
async def wiki_build(
    file: UploadFile = File(..., description="文物 Excel（.xls/.xlsx）"),
    museum_name: str | None = Form(
        default=None, description="博物馆名称（可选，默认从文件名推断）"
    ),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="缺少文件名")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="上传文件为空")
    try:
        return build_wiki_from_upload(
            content,
            file.filename,
            museum_name=museum_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"构建失败：{exc}") from exc


@app.post(
    "/api/v1/chat",
    summary="博物馆讲解对话",
    responses={
        200: {
            "description": "stream=true 时为 text/plain 流；否则 JSON {\"message\":\"...\"}",
        }
    },
)
async def museum_chat(req: ChatRequest):
    if not req.museum_name.strip():
        raise HTTPException(status_code=400, detail="museum_name 不能为空")
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="question 不能为空")

    try:
        if req.stream:
            return StreamingResponse(
                chat_stream(req),
                media_type="text/plain; charset=utf-8",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )
        message = await chat(req)
        return ChatResponse(message=message)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"对话失败：{exc}") from exc


@app.post(
    "/api/v1/chat/complete",
    response_model=ChatResponse,
    summary="博物馆讲解对话（非流式 JSON）",
)
async def museum_chat_complete(req: ChatRequest):
    req.stream = False
    try:
        message = await chat(req)
        return ChatResponse(message=message)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"对话失败：{exc}") from exc
