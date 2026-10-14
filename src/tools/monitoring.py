def query_disk_history(host: str, mount: str) -> dict:
    """
    查询磁盘历史使用率。
        host:主机
        mount:挂载点
    """

    return {
        "host": host,
        "mount": mount,
        "history": [
            {"time": "08:00", "usage": 82},
            {"time": "10:00", "usage": 85},
            {"time": "12:00", "usage": 87},
            {"time": "14:00", "usage": 89},
            {"time": "16:00", "usage": 92},
        ],
        "trend": "持续增长",
    }
