"""Run one live AI investigation against the bootstrap incident and print a compact report."""
import json
import sys
import uuid

from app.api.routes import ser_investigation
from app.db.models import Incident
from app.db.session import SessionLocal
from app.investigator.agent import run_ai_investigation, run_baseline_investigation

mode = sys.argv[1] if len(sys.argv) > 1 else "AI"
boot = json.load(open("../reports/sandbox-bootstrap.json"))
with SessionLocal() as s:
    inc = s.get(Incident, uuid.UUID(boot["incident_id"]))
    run = run_ai_investigation(s, inc) if mode == "AI" else run_baseline_investigation(s, inc)
    s.commit()
    d = ser_investigation(s, run)
    print("status", d["status"], "calls", d["tool_calls_used"], "latency_ms", d["latency_ms"], "tokens",
          d["input_tokens"], d["output_tokens"], "err", (d["error"] or "")[:400])
    for t in d["tool_calls"]:
        print(" ", t["query_id"], t["tool"], json.dumps(t["arguments"]), t["status"])
    f = d["finding"]
    if f:
        print("ROOT", f["root_cause"], "conf", f["confidence"], "action", f["recommended_action"], "verified",
              f["verified_claims"], "unsupported", f["unsupported_claims"])
        print("EXPL", f["explanation"][:800])
        print("UNC", f["uncertainty"][:300])
        for e in f["evidence"]:
            print("  -", e["verification"], e["query_id"], e["metric_path"], e["claimed_value"], "src=",
                  e["source_value"], e["reason"] or "")
        print("SECONDARY", json.dumps([t for t in d["trace"] if t.get("step") == "secondary_causes"]))
