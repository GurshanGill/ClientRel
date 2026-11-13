import os

from pymongo import MongoClient
from redis import Redis

STREAM = "clientrel:ingestion"
GROUP = "clientrel:workers"
db = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"),
                 serverSelectionTimeoutMS=4000).clientrel
queue = Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379"), decode_responses=True)
