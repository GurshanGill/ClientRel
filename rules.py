"""Compile a bounded query plan into a read-only MongoDB pipeline."""
import json
import math
import os
from urllib.request import Request, urlopen

FIELDS = {
    "name": str, "email": str, "company": str, "industry": str,
    "region": str, "stage": str, "value": float,
}
OPERATORS = {"eq": "$eq", "gt": "$gt", "gte": "$gte", "lt": "$lt", "lte": "$lte"}

def model_plan(question):
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise ValueError("Configure OPENAI_API_KEY to run AI queries.")
    guide = (
        "Translate the user's CRM analytics request into a JSON object with exactly these keys: "
        "filters (array of {field, op, value}), group_by (field or null), "
        "metric (list, count, sum, or avg), sort (asc or desc), limit (integer 1-100). "
        f"Fields: {', '.join(FIELDS)}. Only value is numeric. "
        "Filter operators: eq, gt, gte, lt, lte. sum and avg always use value. "
        "list cannot group and sorts by deal value. Grouped metrics sort by result. "
        "Use an empty filter array when appropriate. If unsupported return {\"error\":true}."
    )
    payload = {
        "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        "response_format": {"type": "json_object"},
        "max_completion_tokens": 800,
        "messages": [{"role": "system", "content": guide}, {"role": "user", "content": question}],
    }
    request = Request("https://api.openai.com/v1/chat/completions", json.dumps(payload).encode(),
                      {"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    with urlopen(request, timeout=25) as response:
        return json.loads(json.load(response)["choices"][0]["message"]["content"])

def compile_plan(plan):
    if not isinstance(plan, dict) or set(plan) != {"filters", "group_by", "metric", "sort", "limit"}:
        raise ValueError("This question could not be represented as a supported CRM query.")
    filters, group, metric, sort, limit = (plan[k] for k in ("filters", "group_by", "metric", "sort", "limit"))
    if (metric not in ("list", "count", "sum", "avg") or sort not in ("asc", "desc")
        or type(limit) is not int or not 1 <= limit <= 100
        or (group is not None and (not isinstance(group, str) or group not in FIELDS))
        or (metric == "list" and group is not None)
        or not isinstance(filters, list) or len(filters) > 8):
        raise ValueError("The query plan exceeds the supported rules.")
    pipeline = []
    conditions = []
    for rule in filters:
        if not isinstance(rule, dict) or set(rule) != {"field", "op", "value"}:
            raise ValueError("Invalid filter.")
        field, op, value = rule["field"], rule["op"], rule["value"]
        if not isinstance(field, str) or field not in FIELDS or not isinstance(op, str) or op not in OPERATORS:
            raise ValueError("Unknown field or operator.")
        if field == "value":
            if type(value) not in (int, float) or not -1e15 <= value <= 1e15 or not math.isfinite(value):
                raise ValueError("Invalid numeric filter.")
        elif op != "eq" or not isinstance(value, str) or len(value) > 200:
            raise ValueError("Text filters require a short equality value.")
        conditions.append({field: {OPERATORS[op]: value}})
    if conditions:
        pipeline.append({"$match": {"$and": conditions}})
    direction = 1 if sort == "asc" else -1
    if metric == "list":
        return pipeline + [{"$sort": {"value": direction, "_id": 1}}, {"$limit": limit},
                           {"$project": {"_id": 0, **dict.fromkeys(FIELDS, 1)}}]
    accumulator = {"count": {"$sum": 1}, "sum": {"$sum": "$value"}, "avg": {"$avg": "$value"}}[metric]
    return pipeline + [{"$group": {"_id": f"${group}" if group else None, "result": accumulator}},
                       {"$sort": {"result": direction, "_id": 1}}, {"$limit": limit},
                       {"$project": {"_id": 0, "group": "$_id", "result": 1}}]
