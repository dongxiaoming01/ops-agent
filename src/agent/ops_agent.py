
from agentscope.agent import ReActAgent
from agentscope.formatter import DashScopeChatFormatter
from agentscope.memory import InMemoryMemory
from agentscope.model import DashScopeChatModel
from agentscope.tool import Toolkit

from config import DASHSCOPE_API_KEY, MODEL_NAME

from skills.alert_analysis.skill import analyze_alert
from skills.fault_diagnosis.skill import diagnose_fault
from skills.duty_handover.skill import generate_handover


def create_ops_agent() -> ReActAgent:
    if not DASHSCOPE_API_KEY:
        raise RuntimeError(
            "请在 .env 中配置 DASHSCOPE_API_KEY"
        )

    toolkit = Toolkit()

    # 注册业务 Skill
    toolkit.register_tool_function(analyze_alert)
    toolkit.register_tool_function(diagnose_fault)
    toolkit.register_tool_function(generate_handover)

    model = DashScopeChatModel(
        model_name=MODEL_NAME,
        api_key=DASHSCOPE_API_KEY,
        stream=False,
    )

    agent = ReActAgent(
        name="ops_agent",
        sys_prompt="""
你是智能运维 Agent，负责协助运维人员分析告警、
定位故障和生成值班交班摘要。

你可以使用以下业务能力：
1. analyze_alert：告警分析，输入告警ID。
2. diagnose_fault：故障定位，输入告警ID和故障现象。
3. generate_handover：值班交班，汇总近期告警。

工作原则：
- 根据用户意图自主选择合适的 Skill。
- 必须基于查询结果分析，不得编造数据。
- 告警分析要说明风险等级、判断依据、可能原因和处置建议。
- 故障定位要区分已知事实、可能原因和后续排查步骤。
- 值班交班要突出未恢复告警、处理进度和待办事项。
- 不得将模拟数据描述为真实生产数据。
- 不得擅自执行生产操作。
- 对于扩容、重启、变更等操作，只能提供建议或准备草稿。
""",
        model=model,
        formatter=DashScopeChatFormatter(),
        toolkit=toolkit,
        memory=InMemoryMemory(),
    )

    return agent


ops_agent = create_ops_agent()