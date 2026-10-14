import yaml
from agentscope.app.storage import RedisStorage

with open("../conf/db.yml", "r") as f:
    conf = yaml.load(f, Loader=yaml.FullLoader)

REDIS_HOST = conf.get("REDIS_HOST")
REDIS_PORT = int(conf.get("REDIS_PORT"))
REDIS_DB = int(conf.get("REDIS_DB"))
REDIS_PASSWORD = conf.get("REDIS_PASSWORD") or None
REDIS_KEY_TTL = int(conf.get("REDIS_KEY_TTL"))


def make_storage() -> RedisStorage:
    """RedisStorage 在当前请求的事件循环内创建并关闭连接池。"""
    return RedisStorage(
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=REDIS_DB,
        password=REDIS_PASSWORD,
        key_ttl=REDIS_KEY_TTL,
    )


redis_storage = make_storage()
