import yaml

with open("../conf/model.yml", "r") as f:
    model_yml = yaml.load(f, Loader=yaml.FullLoader)

OPENAI_API_KEY = model_yml.get("OPENAI").get("api-key")
OPENAI_BASE_URL = model_yml.get("OPENAI").get("base-url")
MODEL_NAME = model_yml.get("OPENAI").get("model-name")