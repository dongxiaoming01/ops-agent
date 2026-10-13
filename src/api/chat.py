import asyncio
import json
import logging
import os
import re
import time
import uuid
from typing import Any

from agentscope.app.storage import RedisStorage, SessionConfig
from agentscope.event import (
    ToolCallStartEvent,
    ToolCallDeltaEvent,
    ToolCallEndEvent,
    ToolResultEndEvent,
)
from agentscope.message import Msg
from agentscope.state import AgentState
from flask import jsonify, request, Response
from flask.views import MethodView

from agent.ops_agent import create_agent
from conf.model import API_KEY, MODEL_ID

logger = logging.getLogger(__name__)

# RedisStorage 的连接参数通过环境变量配置。
REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD") or None
REDIS_KEY_TTL = int(os.getenv("REDIS_KEY_TTL", "604800"))  # 默认 7 天


# ============================================================
# Open WebUI 请求头
# ============================================================
def read_openwebui_headers() -> dict[str, str | None]:
    return {
        "user_id": request.headers.get("X-OpenWebUI-User-Id").strip(),
        "agent_id": MODEL_ID,
        "session_id": request.headers.get("X-OpenWebUI-Chat-Id").strip(),
        #以下变量未使用
        "task": request.headers.get("X-OpenWebUI-Task").strip(),
        "user_name": request.headers.get("X-OpenWebUI-User-Id").strip(),
        "user_email": request.headers.get("X-OpenWebUI-User-Email").strip(),
        "user_role": request.headers.get("X-OpenWebUI-User-Role").strip(),
    }


def check_api_key():
    if request.headers.get("Authorization") != f"Bearer {API_KEY}":
        return jsonify({"error": {"message": "Invalid API key"}}), 401
    return None


# ============================================================
# 消息处理
# ============================================================


def content_to_text(content: Any) -> str:
    """兼容 OpenAI 字符串及多模态内容列表中的文本块。"""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""

    texts = []
    for block in content:
        if isinstance(block, dict):
            block_type = block.get("type")
            text = block.get("text", "")
        else:
            block_type = getattr(block, "type", None)
            text = getattr(block, "text", "")
        if text and block_type in ("text", None):
            texts.append(str(text))
    return "".join(texts)


def is_auxiliary_task(text: str) -> str | None:
    """兼容从请求正文识别的 Open WebUI 标题和 follow-up 辅助任务。"""
    text_lower = text.lower()
    if "### task:" not in text_lower:
        return None

    if any(x in text_lower for x in ("follow_ups", "follow-up questions", "follow up questions")):
        return "followups"
    if "title" in text_lower and any(
            x in text_lower for x in ("json", "chat_history", "chat history")
    ):
        return "title"
    return "other"


def auxiliary_task_from_header(task: str | None) -> str | None:
    if not task:
        return None
    task_lower = task.lower().replace("-", "_")
    if "follow_up" in task_lower or "followup" in task_lower:
        return "followups"
    if "title" in task_lower:
        return "title"
    return None


def extract_first_user_message(task_text: str) -> str:
    match = re.search(r"USER:\s*(.+)", task_text, flags=re.IGNORECASE)
    if not match:
        return "智能运维助手"
    return match.group(1).strip()[:40] or "智能运维助手"


def latest_user_text(messages: list[dict]) -> str:
    for item in reversed(messages):
        if item.get("role") == "user":
            text = content_to_text(item.get("content", "")).strip()
            if text and not is_auxiliary_task(text):
                return text
    return ""


# ============================================================
# OpenAI 兼容响应
# ============================================================


def completion_response(answer: str, stream: bool = False):
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())

    if not stream:
        return jsonify({
            "id": completion_id,
            "object": "chat.completion",
            "created": created,
            "model": MODEL_ID,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": answer},
                "finish_reason": "stop",
            }],
        })

    # 保留当前项目的 SSE 兼容方式；此版本仍是单个内容 chunk，而非 token 级流式。
    def generate():
        first_chunk = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": MODEL_ID,
            "choices": [{
                "index": 0,
                "delta": {"role": "assistant", "content": answer},
                "finish_reason": None,
            }],
        }
        yield f"data: {json.dumps(first_chunk, ensure_ascii=False)}\n\n"
        final_chunk = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": MODEL_ID,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
        yield f"data: {json.dumps(final_chunk, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return Response(
        generate(),
        content_type="text/event-stream; charset=utf-8",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def auxiliary_response(task_type: str, task_text: str):
    if task_type == "title":
        title = re.sub(r"\s+", " ", extract_first_user_message(task_text)).strip()
        if len(title) > 24:
            title = title[:24].rstrip() + "…"
        return completion_response(json.dumps({"title": title}, ensure_ascii=False))

    if task_type == "followups":
        if re.search(r"[\u4e00-\u9fff]", task_text):
            suggestions = [
                "如何接入实际监控数据进行告警分析？",
                "如何根据告警自动生成故障排查步骤？",
                "如何为运维操作增加人工确认机制？",
            ]
        else:
            suggestions = [
                "How can I connect real monitoring data?",
                "How can I generate troubleshooting steps from alerts?",
                "How can I add human approval before operations?",
            ]
        return completion_response(json.dumps({"follow_ups": suggestions}, ensure_ascii=False))

    return jsonify({"error": {"message": "Unsupported auxiliary task"}}), 400


# ============================================================
# Skill 事件监控
# ============================================================

async def reply_with_skill_monitor(agent, message: Msg):
    skill_prompt = await agent.toolkit.get_skill_instructions()
    logger.info(
        "[Skill注册检查] %s",
        skill_prompt if skill_prompt else "未发现已注册的 Skill",
    )
    schemas = await agent.toolkit.get_tool_schemas()
    tool_names = [item.get("function", {}).get("name", item.get("name")) for item in schemas]
    logger.info("[工具注册检查] %s", tool_names)

    skill_args_buffer: dict[str, str] = {}
    pending_skills: dict[str, str] = {}
    used_skills = []
    final_msg = None

    async for event in agent.reply_stream(message, yield_final_msg=True):
        if isinstance(event, ToolCallStartEvent) and event.tool_call_name == "Skill":
            skill_args_buffer[event.tool_call_id] = ""
            logger.info("[Skill监控] 开始调用 Skill，call_id=%s", event.tool_call_id)
        elif isinstance(event, ToolCallDeltaEvent) and event.tool_call_id in skill_args_buffer:
            skill_args_buffer[event.tool_call_id] += event.delta
        elif isinstance(event, ToolCallEndEvent) and event.tool_call_id in skill_args_buffer:
            raw_args = skill_args_buffer.pop(event.tool_call_id)
            try:
                args = json.loads(raw_args)
                skill_name = args.get("skill", "unknown")
            except (json.JSONDecodeError, AttributeError):
                skill_name = "unknown"
            pending_skills[event.tool_call_id] = skill_name
            logger.info("[Skill监控] Agent请求加载技能：%s，参数=%s", skill_name, raw_args)
        elif isinstance(event, ToolResultEndEvent) and event.tool_call_id in pending_skills:
            skill_name = pending_skills.pop(event.tool_call_id)
            state = str(getattr(event.state, "value", event.state)).lower()
            if state.endswith("success"):
                used_skills.append(skill_name)
                logger.info("[Skill监控] 技能读取成功：%s", skill_name)
            else:
                logger.warning("[Skill监控] 技能读取未成功：%s，状态=%s", skill_name, state)
        elif isinstance(event, Msg):
            final_msg = event

    if final_msg is None:
        raise RuntimeError("Agent 未返回最终消息，请检查是否发生了中断或等待用户确认。")
    return final_msg, list(dict.fromkeys(used_skills))


# ============================================================
# RedisStorage 会话上下文
# ============================================================


def make_storage() -> RedisStorage:
    """RedisStorage 在当前请求的事件循环内创建并关闭连接池。"""
    return RedisStorage(
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=REDIS_DB,
        password=REDIS_PASSWORD,
        key_ttl=REDIS_KEY_TTL,
    )



async def process_chat(*, headers: dict[str, str | None], current_text: str, ) -> str:
    user_id = headers["user_id"]
    agent_id = headers["agent_id"]
    session_id = headers["session_id"]

    async with make_storage() as storage:
        record = await storage.get_session(
            user_id=user_id,
            agent_id=agent_id,
            session_id=session_id,
        )
        if record is None:
            state = AgentState()
            await storage.upsert_session(
                user_id=user_id,
                agent_id=agent_id,
                session_id=session_id,
                config=SessionConfig(workspace_id="",name="",),
                state=state,
            )
        else:
            state = record.state

        message = Msg(
            name="user",
            content=[{"type": "text", "text": current_text}],
            role="user",
        )

        agent = create_agent(state)
        result, used_skills = await reply_with_skill_monitor(agent, message)
        answer = content_to_text(getattr(result, "content", []))
        if not answer.strip():
            raise RuntimeError("智能体返回了空内容")
        await storage.update_session_state(
            user_id=user_id,
            agent_id=agent_id,
            session_id=session_id,
            state=agent.state,
        )
        return answer


class ChatAPI(MethodView):
    @staticmethod
    def post():
        error = check_api_key()
        if error:
            return error

        body = request.get_json(silent=True) or {}
        messages = body.get("messages", [])
        if not isinstance(messages, list) or not messages:
            return jsonify({"error": {"message": "messages 不能为空"}}), 400

        headers = read_openwebui_headers()
        last_content = content_to_text(messages[-1].get("content", ""))

        # 优先使用 Open WebUI 的 Task 请求头识别辅助任务，兼容原来的正文检测方式。
        task_type = auxiliary_task_from_header(headers["task"]) or is_auxiliary_task(last_content)
        if task_type:
            return auxiliary_response(task_type, last_content)
        if is_auxiliary_task(last_content) == "other":
            return jsonify({"error": {"message": "Unsupported auxiliary task"}}), 400

        current_text = latest_user_text(messages)
        if not current_text:
            return jsonify({"error": {"message": "没有可处理的用户文本消息"}}), 400

        try:
            answer = asyncio.run(
                process_chat(headers=headers, current_text=current_text)
            )
        except ValueError as exc:
            return jsonify({"error": {"message": str(exc)}}), 400
        except Exception:
            logger.exception("AgentScope / RedisStorage 调用失败")
            return jsonify({
                "error": {"message": "智能体调用失败，请查看服务端日志"},
            }), 500

        logger.info(
            "模型请求处理成功，session_id=%s，OpenWebUI消息数=%d，回复长度=%d",
            headers["session_id"],
            len(messages),
            len(answer),
        )
        return completion_response(answer, stream=bool(body.get("stream", False)))
