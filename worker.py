import json
import logging
import os
import time
from uuid import uuid4

from pymongo import UpdateOne
from redis.exceptions import ResponseError

from data import normalize, record_id
from storage import db, queue, STREAM, GROUP

def process(message_id, message):
    job = message["job"]
    chunk = int(message["chunk"])
    operations = []
    rejected = 0
    for index, row in enumerate(json.loads(message["rows"])):
        try:
            record = normalize(row)
        except ValueError:
            rejected += 1
            continue
        identity = record_id(job, f"{chunk}:{index}")
        operations.append(UpdateOne({"_id": identity}, {"$setOnInsert": record}, upsert=True))
    if operations:
        db.contacts.bulk_write(operations, ordered=False)
    db.receipts.update_one({"_id": f"{job}:{chunk}"},
                           {"$setOnInsert": {"job": job, "accepted": len(operations), "rejected": rejected}},
                           upsert=True)
    with queue.pipeline(transaction=True) as transaction:
        transaction.xack(STREAM, GROUP, message_id)
        transaction.xdel(STREAM, message_id)
        transaction.execute()

def main():
    consumer = f"{os.uname().nodename}-{uuid4()}"
    db.receipts.create_index("job")
    db.contacts.create_index([("stage", 1), ("_id", 1)])
    try:
        queue.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
    except ResponseError as error:
        if "BUSYGROUP" not in str(error):
            raise
    cursor = "0-0"
    while True:
        try:
            cursor, stale, _ = queue.xautoclaim(STREAM, GROUP, consumer, 60_000, cursor, count=1)
            incoming = [] if stale else queue.xreadgroup(GROUP, consumer, {STREAM: ">"}, count=1, block=1000)
            for message_id, message in stale or (incoming[0][1] if incoming else []):
                process(message_id, message)
        except Exception:
            logging.exception("Worker operation failed")
            time.sleep(2)

if __name__ == "__main__":
    main()
