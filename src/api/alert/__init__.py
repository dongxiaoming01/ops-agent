from flask import Blueprint

from api.alert.alert_analysis_api import AlertAnalysisAPI, AlertAnalysisHumanAPI

alert_bp = Blueprint('alert', __name__)
alert_bp.add_url_rule("/analysis",view_func=AlertAnalysisAPI.as_view("analysis"),methods=['POST'])
alert_bp.add_url_rule("/analysis/human",view_func=AlertAnalysisHumanAPI.as_view("analysis_human"),methods=['POST'])