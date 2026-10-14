from .alert import get_alert_by_id
from .monitoring import query_disk_history

TOOLS = [query_disk_history, get_alert_by_id]
