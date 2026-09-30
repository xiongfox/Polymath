## 一、博物馆Wiki目录结构说明
### 1、系统级别博物馆信息路径：/wiki/index.md  博物馆名称（主要用于博物馆切换）
### 2、具体博物馆信息路径：   /wiki/museum/博物馆名称/index.md 博物馆的总索引（基础概况、展厅列表、馆藏文物分类索引）
    如：/wiki/museum/南京博物院/index.md
### 3、具体展厅信息路径：     /wiki/exhibition/博物馆名称/展厅名称.md
    如：/wiki/exhibition/南京博物院/历史馆1展厅.md
### 4、具体文物信息路径：     /wiki/cultural_relic/博物馆名称/文物名称.md
    如：/wiki/cultural_relic/南京博物院/白瓷器盏托.md

## 二、博物馆Wiki使用说明
### 1、当识别到用户有切换博物馆的意图时，加载/wiki/index.md 文档
### 2、当识别到用户询问展厅讲解的意图时(局限于展厅有什么文物、展厅的位置)，加载wiki/exhibition/博物馆名称/展厅名称.md
### 3、当识别到用户询问文物讲解的意图时(特别注意的是文物在哪个展厅属于文物讲解意图)，加载/wiki/cultural_relic/博物馆名称/文物名称.md


## 三、博物馆Agent设计说明
### 1、整个ai讲解agent使用langgraph+langchain+llmwiki 不使用RAG；
### 2、整个流程为：选择博物馆--意图识别--根据意图类型加载对应的wiki文档--组装提示词--请求LLM模型

## 四、运行博物馆讲解 Agent

### 环境
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
ollama pull qwen3:8b
cp .env.example .env
```

### 启动多轮对话
```bash
python main.py
# 仅规则意图识别（不调 LLM 做意图）：
python main.py --no-llm-intent
```

### 意图与主体识别说明
| 意图 | 触发场景 | 加载 Wiki |
|------|----------|-----------|
| switch_museum | 切换/列举博物馆 | `wiki/index.md` |
| museum_overview | 博物馆概况、展厅列表 | `wiki/museum/{馆}/index.md` |
| exhibition | 展厅位置、厅内有哪些文物 | `wiki/exhibition/{馆}/{厅}.md` |
| cultural_relic | 文物讲解；**含「文物在哪个展厅」** | `wiki/cultural_relic/{馆}/{文物}.md` |

识别策略：**Wiki 实体最长子串匹配（规则）→ 未命中时 LLM 结构化补全 → 结果约束在索引内防幻觉**。

### FastAPI 对外集成

```bash
pip install -r requirements.txt
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

| 接口 | 说明 |
|------|------|
| `POST /api/v1/wiki/build` | `multipart/form-data` 上传 Excel，触发 Wiki 构建（逻辑同 `src/excel2md_museum_index.py`） |
| `POST /api/v1/chat` | 对话；`stream=true`（默认）返回 **纯文本流**，`stream=false` 返回 `{"message":"..."}` |
| `POST /api/v1/chat/complete` | 非流式 JSON（同上，仅 `message` 字段） |
| `GET /health` | 健康检查 |

对话请求体示例（**每次请求请携带完整 `history`**，服务端据此做多轮意图识别）：

```json
{
  "museum_name": "南京博物院",
  "question": "2",
  "history": [
    {"role": "user", "content": "介绍下三彩马"},
    {"role": "assistant", "content": "馆藏中有 2 件文物与「三彩马」相关…（上一轮助手完整回复）"}
  ],
  "stream": true
}
```

响应仅含聊天正文：非流式 `{"message":"..."}`；流式为 `text/plain` 逐段文本，无 intent/meta 字段。

### 文物简称消歧
用户可能用简称提问（如「釉陶壶」对应「釉陶壶2/6/7/8/16」）。系统将：
1. 列出所有匹配的馆藏文物名称，引导用户选择；
2. 用户可回复完整名称（「釉陶壶6」）或序号（「选 2」「第 3 个」）；
3. 选定后再加载对应 Wiki 并生成讲解。
    