def get_alert_by_id(alert_id: str) -> dict:
    """
    根据告警ID查询告警详情。
    参数:
        alert_id: 告警ID
    返回:告警详细信息
    """
    mock_alerts = [
        {
            "alert_id": "123",
            "host": "app01",
            "mount": "/opt",
            "metric": "disk_usage",
            "value": 92,
            "severity": "warning"
        },
        {
            "alert_id": "234",
            "host": "app01",
            "mount": "/opt",
            "metric": "disk_usage",
            "value": 99,
            "severity": "warning"
        }
    ]
    alert = {alert.get('alert_id'): alert for alert in mock_alerts}.get(alert_id)
    return alert
