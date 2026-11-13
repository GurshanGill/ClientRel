import hashlib
import math

STAGES = ("New", "Qualified", "Proposal", "Won", "Lost")

def normalize(row):
    result = {}
    for key in ("name", "email", "company", "industry", "region", "stage"):
        value = row.get(key)
        if value is None or not isinstance(value, str) or len(value.strip()) > 200:
            raise ValueError(f"Invalid {key}")
        result[key] = value.strip()
    result["email"] = result["email"].lower()
    if not result["name"] or result["email"].count("@") != 1 or not all(result["email"].split("@")):
        raise ValueError("Name and a valid email are required")
    if result["stage"] not in STAGES:
        raise ValueError("Unknown stage")
    try:
        result["value"] = float(row.get("value", ""))
    except (ValueError, TypeError):
        raise ValueError("Value must be numeric") from None
    if not math.isfinite(result["value"]) or not 0 <= result["value"] <= 1e12:
        raise ValueError("Value is outside the supported range")
    return result

def record_id(job, index):
    return hashlib.sha256(f"{job}:{index}".encode()).hexdigest()

def demo_rows():
    names = ["Olivia Rhye", "Phoenix Baker", "Lana Steiner", "Demi Wilkinson", "Candice Wu",
             "Natali Craig", "Drew Cano", "Orlando Diggs", "Andi Lane", "Kate Morrison"]
    companies = ["Layers", "Sisyphus", "Catalog", "Hourglass", "Quotient",
                 "Circooles", "Command+R", "Nietzsche", "Capsule", "Spherule"]
    return [
        dict(name=names[i], company=companies[i], email=f'{names[i].split()[0].lower()}@{companies[i].lower().replace("+", "")}.example',
             stage=STAGES[(i * 3 + 1) % 5], industry=["Software", "Finance", "Retail"][i % 3],
             region=["North America", "Europe", "Asia Pacific"][i % 3],
             value=[42000, 28500, 64000, 18500, 36000, 51000, 24000, 13500, 20500, 32000][i])
        for i in range(len(names))
    ]
