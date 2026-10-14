from pathlib import Path

from agentscope.agent import Agent, InjectionConfig
from agentscope.credential import DashScopeCredential
from agentscope.model import DashScopeChatModel
from agentscope.permission import PermissionBehavior, PermissionDecision
from agentscope.state import AgentState
from agentscope.tool import FunctionTool, Toolkit

from conf.model import DASHSCOPE_API_KEY, MODEL_ID
from tools import get_alert_by_id, query_disk_history
from tools.pdf_report import generate_pdf_report

BASE_DIR = Path(__file__).resolve().parent.parent
SKILL_DIR = BASE_DIR / "skills" / "alert_analysis"

SYSTEM_PROMPT = """
你是智能运维助手，负责生产环境告警分析与故障定位。

当用户请求分析告警、排查故障或定位异常时，必须优先使用
AgentScope 内置的 Skill 工具读取 alert_analysis 的完整 SKILL.md。

执行顺序：
1. 先调用 Skill 工具读取 alert_analysis。
2. 成功读取技能内容后，再调用告警和监控查询工具。
3. 严格遵循 Skill 中的分析流程和输出格式。
4. 未成功读取 Skill 前，不得开始调用业务查询工具。
5. 如果 Skill 读取失败，明确报告失败，不得假装已执行该技能。

其他类型的问题不必调用告警分析 Skill。

回答应准确、清晰、简洁，不得编造监控数据。
涉及生产环境变更或执行操作时，必须先获得用户确认。
"""

READ_ONLY_PERMISSION = PermissionDecision(
    behavior=PermissionBehavior.ALLOW, message="只读查询工具，允许自动执行。"
)


def create_agent(state: AgentState) -> Agent:
    """每次请求创建独立 Agent，避免进程内共享 Agent 状态导致会话串线。"""
    if not DASHSCOPE_API_KEY:
        raise RuntimeError("未配置 DASHSCOPE_API_KEY，请检查项目根目录 .env")

    if not (SKILL_DIR / "SKILL.md").is_file():
        raise FileNotFoundError(f"未找到 Skill 文件：{SKILL_DIR / 'SKILL.md'}")

    tools = [
        FunctionTool(
            get_alert_by_id, is_read_only=True, permission=READ_ONLY_PERMISSION
        ),
        FunctionTool(
            query_disk_history, is_read_only=True, permission=READ_ONLY_PERMISSION
        ),
        FunctionTool(
            generate_pdf_report, is_read_only=False, permission=READ_ONLY_PERMISSION
        ),
    ]

    toolkit = Toolkit(tools=tools, skills_or_loaders=[str(SKILL_DIR)])

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
