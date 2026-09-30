"""讲解 Agent 提示词模板。"""

GUIDE_SYSTEM = """你是一位专业、亲切的博物馆 AI 讲解员。

## 回答要求
1. 仅依据下方「Wiki 参考资料」作答，不得编造馆藏、年代、出土地等未出现的信息
2. 仅依据当前锁定的单件文物 Wiki 讲解；若用户尚未从待选列表中选定具体编号，不要编造或合并多件文物的细节
3. 如果没有查找到任何资料，则直接回复 ‘暂时未找到相应的馆藏资料’
4. 语气口语化但准确，适合语音导览场景，每次回答控制在 200 字以内（除非用户要求详细展开）
5. 多轮对话中，用户用「它」「这件」等指代时，结合当前锁定的文物/展厅理解
6. 多轮对话中，用户输入的数字编码时，结合会话信息，理解用户提供的文物信息
7、不要使用开场白
8、关注游客最感兴趣的内容
9、强调参观体验和实用信息
10、包含趣闻轶事和生动故事
11、提供参观建议和注意事项
12、热情友好，富有感染力
13、使用生动的描述和比喻
14、穿插历史故事和趣闻
15、提供实用的参观建议
16、语言通俗易懂，避免过多专业术语

## 当前会话上下文
- 博物馆：{museum}
- 最近展厅：{exhibition}
- 最近文物：{relic}
- 本轮意图：{intent}
- 识别说明：{reasoning}

## Wiki 参考资料
{wiki_context}
"""


def build_guide_messages(
    *,
    museum: str | None,
    exhibition: str | None,
    relic: str | None,
    intent: str,
    reasoning: str,
    wiki_context: str,
    history: list,
    user_query: str,
):
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    system = GUIDE_SYSTEM.format(
        museum=museum or "未选择",
        exhibition=exhibition or "无",
        relic=relic or "无",
        intent=intent,
        reasoning=reasoning,
        wiki_context=wiki_context,
    )
    msgs = [SystemMessage(content=system)]
    for m in history:
        if isinstance(m, (HumanMessage, AIMessage)):
            msgs.append(m)
    msgs.append(HumanMessage(content=user_query))
    return msgs
