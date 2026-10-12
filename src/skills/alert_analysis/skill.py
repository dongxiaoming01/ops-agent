
from agentscope.tool import ToolResponse

from tools.monitoring import query_disk_history
from tools.alert import get_alert_by_id


def analyze_alert(alert_id: str) -> ToolResponse:
    """执行告警分析 Skill，获取告警详情和历史趋势。

    Args:
        alert_id (str): 需要分析的告警ID。
    """
    alert_result = get_alert_by_id(alert_id)

    # 第一版先根据告警详情提取查询参数。
    # 接入真实平台后，建议将 Tool 返回值改为结构化数据，
    # 避免从文本中反向解析字段。
    alert_data = {
        "alert_id": alert_id,
        "host": "10.10.10.100",
        "mount_point": "/data",
    }

    history_result = query_disk_history(
        host=alert_data["host"],
        mount_point=alert_data["mount_point"],
        hours=24,
    )

    return ToolResponse(
        content=[
            {
                "type": "text",
                "text": (
                    "【告警详情】\n"
                    f"{alert_result.content}\n"
                    "【历史监控数据】\n"
                    f"{history_result.content}"
                ),
            }
        ]
    )