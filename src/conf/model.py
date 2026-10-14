import yaml

with open("../conf/model.yml", "r") as f:
    conf = yaml.load(f, Loader=yaml.FullLoader)

MODEL_ID = "ops-agent"
API_KEY = conf.get("OPS_AGENT_API_KEY")
DASHSCOPE_API_KEY = conf.get("DASHSCOPE_API_KEY")
