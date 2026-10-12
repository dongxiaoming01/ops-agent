import json
import time
import uuid

from flask import request, jsonify, Response, stream_with_context
from flask.views import MethodView

from skills.alert_analysis.skill import AlertAnalysisSkill

skill = AlertAnalysisSkill()

class AlertAnalysisAPI(MethodView):
    @staticmethod
    def post():
        alert_id = request.json.get('alert_id')
        session_id = str(uuid.uuid4()).replace("-", "")

        def generate():
            pass
            # stream = skill.run(session_id=session_id,alert_id=alert_id)
            # for chunk in stream:
            #     if "tools" in chunk:
            #         tool_message = chunk["tools"]['messages'][0]
            #         yield f"{tool_message.name}: {tool_message.content}\n\n"
            #     elif "agent" in chunk:
            #         ai_message = chunk["agent"]['messages'][0]
            #         if ai_message.content:
            #             yield f"ai_message: {ai_message.content}\n\n"
            #     elif "__interrupt__" in chunk:
            #         pass
            #     print(time.time())

        return Response(stream_with_context(generate()),content_type="text/event-stream; charset=utf-8")



class AlertAnalysisHumanAPI(MethodView):
    @staticmethod
    def post():
        session_id = request.json.get('session_id')
        confirm: bool = request.json.get('confirm')
        suggest = request.json.get('suggest')
        resume = {
            "confirm": confirm,
            "suggest": suggest
        }

        result = skill.run(session_id, resume=resume)
        return jsonify({
            "success": True,
            "session_id": session_id,
            "data": result
        })
