import logging
import os
from flask import Flask
from flask_cors import CORS
from api import agent_bp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
app = Flask(__name__)
CORS(app)
app.register_blueprint(agent_bp)

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8001")),
        debug=False,
    )
