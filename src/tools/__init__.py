from .monitoring import query_disk_history
from .alert import get_alert_by_id


TOOLS = [
    query_disk_history,
    get_alert_by_id
]