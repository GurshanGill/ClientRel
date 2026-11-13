import csv
import time
import io
import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import URLError
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import uuid4

from data import demo_rows
from rules import FIELDS, compile_plan, model_plan

DEMO = os.environ.get("CLIENTREL_DEMO") == "1"
STATIC = Path(__file__).with_name("static")
MAX_UPLOAD = 256 * 1024 * 1024
CHUNK_SIZE = 500

if not DEMO:
    from storage import db, queue, STREAM

class LimitedBody(io.RawIOBase):
    def __init__(self, stream, size):
        self.stream = stream
        self.remaining = size

    def readable(self):
        return True

    def readinto(self, target):
        if not self.remaining:
            return 0
        data = self.stream.read(min(len(target), self.remaining))
        if not data:
            raise ValueError("Upload ended early.")
        target[:len(data)] = data
        self.remaining -= len(data)
        return len(data)

def enqueue_csv(stream, size, filename):
    with io.TextIOWrapper(io.BufferedReader(LimitedBody(stream, size)), encoding="utf-8-sig", newline="") as body:
        reader = csv.DictReader(body, strict=True)
        if len(reader.fieldnames or []) != len(FIELDS) or set(reader.fieldnames or []) != set(FIELDS):
            raise ValueError("CSV columns must be name, email, company, industry, region, stage, value.")
        job = uuid4().hex
        db.jobs.insert_one({"_id": job, "filename": filename, "status": "uploading", "chunks": 0, "created": time.time()})
        chunk, index, rows = [], 0, 0
        try:
            for row in reader:
                # Preserve a rejected-row receipt without sending oversized cells to Redis.
                chunk.append(row if None not in row and all(isinstance(v, str) and len(v) <= 256 for v in row.values()) else {})
                rows += 1
                if len(chunk) == CHUNK_SIZE:
                    queue.xadd(STREAM, {"job": job, "chunk": index, "rows": json.dumps(chunk)})
                    chunk, index = [], index + 1
            if chunk:
                queue.xadd(STREAM, {"job": job, "chunk": index, "rows": json.dumps(chunk)})
                index += 1
        except Exception:
            db.jobs.update_one({"_id": job}, {"$set": {"status": "upload_failed", "chunks": index}})
            raise
        db.jobs.update_one({"_id": job}, {"$set": {"status": "queued", "chunks": index, "rows": rows}})
        return job

def list_jobs():
    jobs = list(db.jobs.find().sort("created", -1).limit(30))
    receipts = db.receipts.aggregate([
        {"$match": {"job": {"$in": [job["_id"] for job in jobs]}}},
        {"$group": {"_id": "$job", "processed": {"$sum": 1},
                    "accepted": {"$sum": "$accepted"}, "rejected": {"$sum": "$rejected"}}},
    ])
    summaries = {item.pop("_id"): item for item in receipts}
    for job in jobs:
        job.update(summaries.get(job["_id"], {"processed": 0, "accepted": 0, "rejected": 0}))
        if job["status"] == "queued" and job["processed"] == job["chunks"]:
            job["status"] = "complete"
    return jobs

class App(BaseHTTPRequestHandler):
    def send_content(self, body, kind, status=200):
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def reply(self, body, status=200):
        self.send_content(json.dumps(body).encode(), "application/json", status)

    def do_GET(self):
        path = urlsplit(self.path)
        files = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"),
                 "/style.css": ("style.css", "text/css")}
        try:
            if path.path in files:
                filename, kind = files[path.path]
                self.send_content((STATIC / filename).read_bytes(), kind + "; charset=utf-8")
            elif path.path == "/api/overview":
                if DEMO:
                    rows = demo_rows()
                    stats = {"contacts": len(rows), "value": sum(r["value"] for r in rows if r["stage"] != "Lost"),
                             "won": sum(r["stage"] == "Won" for r in rows)}
                    stages = {stage: sum(r["stage"] == stage for r in rows) for stage in ("New", "Qualified", "Proposal", "Won", "Lost")}
                else:
                    metrics = list(db.contacts.aggregate([{"$group": {"_id": "$stage", "count": {"$sum": 1}, "value": {"$sum": "$value"}}}]))
                    stats = {"contacts": sum(r["count"] for r in metrics),
                             "value": sum(r["value"] for r in metrics if r["_id"] != "Lost"),
                             "won": sum(r["count"] for r in metrics if r["_id"] == "Won")}
                    stages = {r["_id"]: r["count"] for r in metrics}
                self.reply({"demo": DEMO, "ai": bool(os.environ.get("OPENAI_API_KEY")) and not DEMO, "stats": stats, "stages": stages})
            elif path.path == "/api/contacts":
                params = parse_qs(path.query)
                search = params.get("q", [""])[0][:120]
                stage = params.get("stage", [""])[0]
                page = max(1, int(params.get("page", ["1"])[0]))
                if page > 1000000:
                    raise ValueError("Page is outside the supported range.")
                offset = (page - 1) * 8
                if DEMO:
                    rows = [r for r in demo_rows() if (not stage or r["stage"] == stage)
                            and any(search.casefold() in r[key].casefold() for key in ("name", "email", "company"))]
                    self.reply({"rows": rows[offset:offset+8], "total": len(rows)})
                else:
                    import re
                    criteria = {"stage": stage} if stage else {}
                    if search:
                        criteria["$or"] = [{key: {"$regex": re.escape(search), "$options": "i"}} for key in ("name", "email", "company")]
                    rows = list(db.contacts.find(criteria, {"_id": 0}).sort("_id", 1).skip(offset).limit(8))
                    self.reply({"rows": rows, "total": db.contacts.count_documents(criteria)})
            elif path.path == "/api/jobs":
                self.reply({"jobs": [] if DEMO else list_jobs()})
            else:
                self.reply({"error": "Page not found."}, 404)
        except ValueError as error:
            self.reply({"error": str(error)}, 400)
        except Exception:
            logging.exception("GET failed")
            self.reply({"error": "CRM data is temporarily unavailable."}, 503)

    def do_POST(self):
        try:
            origin = self.headers.get("Origin")
            if origin and urlsplit(origin).netloc != self.headers.get("Host"):
                self.reply({"error": "Cross-origin writes are disabled."}, 403)
                return
            size = int(self.headers.get("Content-Length", "0"))
            self.connection.settimeout(30)
            if DEMO:
                raise ValueError("Start the connected stack to import data or run AI queries.")
            if self.path == "/api/import" and 0 < size <= MAX_UPLOAD:
                filename = unquote(self.headers.get("X-Filename", "contacts.csv"))[:200]
                self.reply({"job": enqueue_csv(self.rfile, size, filename)}, 202)
            elif self.path == "/api/query" and 0 < size <= 8192:
                body = json.loads(self.rfile.read(size))
                question = body.get("question") if isinstance(body, dict) else None
                if not isinstance(question, str) or not 1 <= len(question.strip()) <= 1000:
                    raise ValueError("Enter a question between 1 and 1,000 characters.")
                pipeline = compile_plan(model_plan(question))
                rows = list(db.contacts.aggregate(pipeline, maxTimeMS=4000, allowDiskUse=False))
                self.reply({"pipeline": pipeline, "rows": rows})
            else:
                raise ValueError("Invalid request size or endpoint. CSV uploads are limited to 256 MiB.")
        except (ValueError, csv.Error) as error:
            self.reply({"error": str(error)}, 400)
        except (URLError, TimeoutError):
            self.reply({"error": "The AI provider or request timed out or was unavailable."}, 502)
        except Exception:
            logging.exception("POST failed")
            self.reply({"error": "The operation could not be completed. Check service logs and import history."}, 503)

if __name__ == "__main__":
    host = "127.0.0.1" if DEMO else "0.0.0.0"
    ThreadingHTTPServer((host, int(os.environ.get("PORT", 8000))), App).serve_forever()
