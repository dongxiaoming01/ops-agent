import asyncio
import json
import logging
import queue
import threading
import time
import uuid
from typing import Any

from agentscope.app.storage import SessionConfig
from agentscope.event import (
    TextBlockDeltaEvent,
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
from conf.redis import redis_storage

logger = logging.getLogger(__name__)

# ============================================================
# Open WebUI 请求头
# ============================================================
def read_openwebui_headers() -> dict[str, str | None]:
    return {
        "user_id": request.headers.get("X-OpenWebUI-User-Id").strip(),
        "agent_id": MODEL_ID,
        "session_id": request.headers.get("X-OpenWebUI-Chat-Id").strip(),
        #以下变量未使用
        "task": request.headers.get("X-OpenWebUI-Task","").strip(),
        "user_name": request.headers.get("X-OpenWebUI-User-Id","").strip(),
        "user_email": request.headers.get("X-OpenWebUI-User-Email","").strip(),
        "user_role": request.headers.get("X-OpenWebUI-User-Role","").strip(),
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

def latest_user_text(messages: list[dict]) -> str:
    for item in reversed(messages):
        if item.get("role") == "user":
            text = content_to_text(item.get("content", "")).strip()
            if text:
                return text
    return ""

# ============================================================
# Skill 事件监控
# ============================================================
async def reply_with_skill_monitor(agent,message: Msg,*,on_text_delta=None,):
    skill_args_buffer: dict[str, str] = {}
    pending_skills: dict[str, str] = {}
    used_skills = []
    final_msg = None
    skill_prompt = await agent.toolkit.get_skill_instructions()
    logger.info("[Skill注册检查] %s", skill_prompt if skill_prompt else "未发现已注册的 Skill", )
    schemas = await agent.toolkit.get_tool_schemas()
    tool_names = [item.get("function", {}).get("name", item.get("name")) for item in schemas]
    logger.info("[工具注册检查] %s", tool_names)

    async for event in agent.reply_stream(message, yield_final_msg=True, ):
        if (isinstance(event, ToolCallStartEvent) and event.tool_call_name == "Skill"):
            skill_args_buffer[event.tool_call_id] = ""
            logger.info("[Skill监控] 开始调用 Skill，call_id=%s", event.tool_call_id, )
        elif (isinstance(event, ToolCallDeltaEvent) and event.tool_call_id in skill_args_buffer):
            skill_args_buffer[event.tool_call_id] += event.delta
        elif (isinstance(event, ToolCallEndEvent) and event.tool_call_id in skill_args_buffer):
            raw_args = skill_args_buffer.pop(event.tool_call_id)
            try:
                args = json.loads(raw_args)
                skill_name = args.get("skill", "unknown")
            except (json.JSONDecodeError, AttributeError):
                skill_name = "unknown"
            pending_skills[event.tool_call_id] = skill_name
            logger.info("[Skill监控] Agent请求加载技能：%s，参数=%s", skill_name, raw_args, )
        elif (isinstance(event, ToolResultEndEvent) and event.tool_call_id in pending_skills):
            skill_name = pending_skills.pop(event.tool_call_id)
            state = str(getattr(event.state, "value", event.state)).lower()
            if state.endswith("success"):
                used_skills.append(skill_name)
                logger.info("[Skill监控] 技能读取成功：%s", skill_name)
            else:
                logger.warning("[Skill监控] 技能读取未成功：%s，状态=%s", skill_name, state, )
        # 将模型生成的文本增量立即交给 HTTP 流式响应层。
        if isinstance(event, TextBlockDeltaEvent) and on_text_delta is not None:
            on_text_delta(event.delta)

        # 无论是否开启监控，都要获取最终回复
        if isinstance(event, Msg):
            final_msg = event

    if final_msg is None:
        raise RuntimeError("Agent 未返回最终消息，请检查是否发生了中断或等待用户确认。")
    return final_msg, list(dict.fromkeys(used_skills))

async def reply_no_skill_monitor(agent,message: Msg,*,on_text_delta=None):
    """执行 Agent 对话，不监控 Skill 调用过程。"""
    final_msg = None
    async for event in agent.reply_stream(message,yield_final_msg=True,):
        if isinstance(event, TextBlockDeltaEvent) and on_text_delta is not None:
            on_text_delta(event.delta)
        if isinstance(event, Msg):
            final_msg = event
    if final_msg is None:
        raise RuntimeError("Agent 未返回最终消息，请检查是否发生了中断或等待用户确认。")
    return final_msg, []


async def process_chat(*,headers: dict[str, str | None],current_text: str,on_text_delta=None,) -> str:
    user_id = headers["user_id"]
    agent_id = headers["agent_id"]
    session_id = headers["session_id"]

    async with redis_storage as storage:
        record = await storage.get_session(user_id=user_id,agent_id=agent_id,session_id=session_id)
        if record is None:
            state = AgentState()
            await storage.upsert_session(user_id=user_id,agent_id=agent_id,session_id=session_id,config=SessionConfig(workspace_id="", name="", ),state=state,)
        else:
            state = record.state

        message = Msg(name="user",content=[{"type": "text", "text": current_text}],role="user",)

        agent = create_agent(state)
        enable_monitor = False
        if enable_monitor:
            result, used_skills = await reply_with_skill_monitor(agent, message, on_text_delta=on_text_delta)
        else:
            result, used_skills = await reply_no_skill_monitor(agent, message, on_text_delta=on_text_delta)
        answer = content_to_text(getattr(result, "content", []))
        if not answer.strip():
            raise RuntimeError("智能体返回了空内容")
        await storage.update_session_state(user_id=user_id,agent_id=agent_id,session_id=session_id,state=agent.state,)
        return answer


def _completion_chunk(completion_id: str, created: int, delta: dict, finish_reason=None) -> str:
    """生成一个 OpenAI Chat Completions SSE chunk。"""
    payload = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": MODEL_ID,
        "choices": [{
            "index": 0,
            "delta": delta,
            "finish_reason": finish_reason,
        }],
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def stream_completion_response(headers: dict[str, str | None], current_text: str):
    """在后台线程运行异步 Agent，并通过队列逐块推送 SSE。"""
    completion_id = f"completion-{uuid.uuid4().hex}"
    created = int(time.time())
    chunks: queue.Queue = queue.Queue()
    sentinel = object()

    def emit_text(text: str) -> None:
        if text:
            chunks.put(_completion_chunk(completion_id, created, {"content": text}))

    def run_agent() -> None:
        try:
            # Flask 的 Response 生成器是同步迭代器，因此用独立线程驱动异步协程。
            asyncio.run(
                process_chat(headers=headers,current_text=current_text,on_text_delta=emit_text)
            )
        except Exception as exc:
            logger.exception("AgentScope 流式调用失败")
            # 已经开始发送 SSE 后，无法再修改 HTTP 状态码；通过流发送错误信息。
            chunks.put("data: " + json.dumps({"error": {"message": "智能体调用失败，请查看服务端日志", "type": type(exc).__name__}},ensure_ascii=False,) + "\n\n")
        finally:
            chunks.put(sentinel)

    def generate():
        # 先发 role chunk，让 OpenAI 兼容客户端识别流开始。
        yield _completion_chunk(completion_id, created, {"role": "assistant"})
        worker = threading.Thread(target=run_agent, daemon=True)
        worker.start()

        while True:
            item = chunks.get()
            if item is sentinel:
                break
            yield item

        yield _completion_chunk(completion_id, created, {}, finish_reason="stop")
        yield "data: [DONE]\n\n"

    return Response(generate(),content_type="text/event-stream; charset=utf-8",headers={"Cache-Control": "no-cache, no-transform","X-Accel-Buffering": "no","Connection": "keep-alive",},)


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
        current_text = latest_user_text(messages)
        if not current_text:
            return jsonify({"error": {"message": "没有可处理的用户文本消息"}}), 400

        # OpenAI 兼容接口：stream=true 时逐段返回文本增量。
        if body.get("stream", False):
            logger.info("开始流式模型请求，session_id=%s，OpenWebUI消息数=%d",headers["session_id"],len(messages),)
            return stream_completion_response(headers, current_text)

        # 以下代码几乎不使用。保留非流式兼容模式，供 stream=false 的客户端使用。
        try:
            answer = asyncio.run(process_chat(headers=headers, current_text=current_text))
        except ValueError as exc:
            return jsonify({"error": {"message": str(exc)}}), 400
        except Exception:
            logger.exception("AgentScope / RedisStorage 调用失败")
            return jsonify({"error": {"message": "智能体调用失败，请查看服务端日志"},}), 500

        logger.info("模型请求处理成功，session_id=%s，OpenWebUI消息数=%d，回复长度=%d",headers["session_id"],len(messages),len(answer))
        completion_id = f"completion-{uuid.uuid4().hex}"
        created = int(time.time())
        return jsonify({"id": completion_id,"object": "chat.completion","created": created,"model": MODEL_ID,"choices": [{"index": 0,"message": {"role": "assistant", "content": answer},"finish_reason": "stop",}]})

