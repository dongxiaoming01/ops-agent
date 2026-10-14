import time

from flask import jsonify, request
from flask.views import MethodView

from conf.model import API_KEY, MODEL_ID


def check_api_key():
    if request.headers.get("Authorization") != f"Bearer {API_KEY}":
        return jsonify({"error": {"message": "Invalid API key"}}), 401
    return None


class HealthAPI(MethodView):
    @staticmethod
    def get():
        return jsonify({"status": "ok"})


class ModelsAPI(MethodView):
    @staticmethod
    def get():
        error = check_api_key()
        if error:
            return error
        return jsonify(
            {
                "object": "list",
                "data": [
                    {
                        "id": MODEL_ID,
                        "object": "model",
                        "created": int(time.time()),
                        "owned_by": "local",
                    }
                ],
            }
        )
