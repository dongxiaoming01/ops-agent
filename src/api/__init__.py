from flask import Blueprint

from api.chat import ChatAPI
from api.download import DownloadAPI
from api.models import HealthAPI, ModelsAPI

agent_bp = Blueprint('agent', __name__)

agent_bp.add_url_rule("/health",view_func=HealthAPI.as_view("health"),methods=['GET'])
agent_bp.add_url_rule("/v1/models",view_func=ModelsAPI.as_view("models"),methods=['GET'])
agent_bp.add_url_rule("/v1/download",view_func=DownloadAPI.as_view("download"),methods=['GET'])
agent_bp.add_url_rule("/v1/chat/completions",view_func=ChatAPI.as_view("chat"),methods=['POST'])