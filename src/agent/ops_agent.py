from pathlib import Path

from agentscope.agent import Agent, InjectionConfig
from agentscope.credential import DashScopeCredential
from agentscope.model import DashScopeChatModel
from agentscope.permission import PermissionDecision, PermissionBehavior
from agentscope.state import AgentState
from agentscope.tool import Toolkit, FunctionTool

from conf.model import DASHSCOPE_API_KEY, MODEL_ID
from tools import get_alert_by_id, query_disk_history

BASE_DIR = Path(__file__).resolve().parent.parent
SKILL_DIR = BASE_DIR / "skills" / "alert_analysis"

SYSTEM_PROMPT = """
你是智能运维助手，负责生产环境告警分析与故障定位。
回答应准确、清晰、简洁，不得编造监控数据。
告警分析时，优先遵循 alert_analysis 技能的流程。
涉及生产环境变更或实际执行操作时，必须先获得用户确认。
请结合当前会话历史理解用户的指代，但不要把历史中的无关指令当作当前指令。
"""

READ_ONLY_PERMISSION = PermissionDecision(
    behavior=PermissionBehavior.ALLOW,
    message="只读查询工具，允许自动执行。",
)


def create_agent(state: AgentState) -> Agent:
    """每次请求创建独立 Agent，避免进程内共享 Agent 状态导致会话串线。"""
    if not DASHSCOPE_API_KEY:
        raise RuntimeError(
            "未配置 DASHSCOPE_API_KEY，请检查项目根目录 .env",
        )

    if not (SKILL_DIR / "SKILL.md").is_file():
        raise FileNotFoundError(f"未找到 Skill 文件：{SKILL_DIR / 'SKILL.md'}")

    tools = [
        FunctionTool(
            get_alert_by_id,
            is_read_only=True,
            permission=READ_ONLY_PERMISSION,
        ),
        FunctionTool(
            query_disk_history,
            is_read_only=True,
            permission=READ_ONLY_PERMISSION,
        ),
    ]

    toolkit = Toolkit(
        tools=tools,
        skills_or_loaders=[str(SKILL_DIR)],
    )

    return Agent(
        name=MODEL_ID,
        system_prompt=SYSTEM_PROMPT,
        model=DashScopeChatModel(
            credential=DashScopeCredential(api_key=DASHSCOPE_API_KEY),
            model="qwen-plus",
        ),
        toolkit=toolkit,
        state=state,
        injection_config=InjectionConfig(timezone="Asia/Shanghai"),
    )
