from agentscope.agent import Agent, InjectionConfig
from agentscope.credential import DashScopeCredential
from agentscope.model import DashScopeChatModel
from agentscope.permission import PermissionDecision, PermissionBehavior
from agentscope.tool import Toolkit, FunctionTool

from conf.model import DASHSCOPE_API_KEY, MODEL_ID
from tools import get_alert_by_id, query_disk_history

system_prompt="""
你是智能运维助手，负责生产环境告警分析与故障定位；
回答应准确、清晰、简洁；
没有查询到实际监控数据时，不得编造监控结果；
涉及生产环境变更或执行操作时，必须先获得用户确认；
请使用用户当前对话的语言回答。
"""

# 只读查询工具：允许 Agent 自主调用
read_only_permission = PermissionDecision(
    behavior=PermissionBehavior.ALLOW,
    message="只读查询工具，允许自动执行。",
)

tools = [
    FunctionTool(
        get_alert_by_id,
        is_read_only=True,
        permission=read_only_permission,
    ),
    FunctionTool(
        query_disk_history,
        is_read_only=True,
        permission=read_only_permission,
    ),
]

def create_agent():
    if not DASHSCOPE_API_KEY:
        raise RuntimeError("未配置 DASHSCOPE_API_KEY，请检查项目根目录 .env")

    return Agent(
        name=MODEL_ID,
        system_prompt=system_prompt,
        model=DashScopeChatModel(
            credential=DashScopeCredential(
                api_key=DASHSCOPE_API_KEY
            ),
            model="qwen-plus",
        ),
        toolkit=Toolkit(tools=tools),
        injection_config=InjectionConfig(
            timezone="Asia/Shanghai",  # 注入该时区的时间
        ),
    )


ops_agent = create_agent()
