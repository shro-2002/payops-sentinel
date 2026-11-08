"""Render docs/task-graph.json (single source of truth) into the Mermaid section of docs/TASK_GRAPH.md."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
g = json.loads((root / "docs/task-graph.json").read_text())
style = {"done": ":::done", "in_progress": ":::wip", "pending": ":::todo", "blocked": ":::blocked"}
lines = ["```mermaid", "flowchart LR"]
for t in g["tasks"]:
    lines.append(f'  {t["id"]}["{t["id"]} {t["title"]}"]{style.get(t["status"], "")}')
for t in g["tasks"]:
    for d in t["depends_on"]:
        lines.append(f"  {d} --> {t['id']}")
lines += ["  classDef done fill:#14532d,color:#fff", "  classDef wip fill:#1e3a8a,color:#fff",
          "  classDef todo fill:#374151,color:#fff", "  classDef blocked fill:#7f1d1d,color:#fff", "```"]
rows = ["| ID | Task | Depends on (consumes output of) | Parallel | Owner files | Verifier | Status | Evidence |",
        "|---|---|---|---|---|---|---|---|"]
for t in g["tasks"]:
    rows.append(f'| {t["id"]} | {t["title"]} | {", ".join(t["depends_on"]) or "-"} | {"yes" if t["parallel"] else "no"} '
                f'| `{", ".join(t["owns"])}` | {t["verifier"]} | {t["status"]} | {t["evidence"]} |')
md = (root / "docs/TASK_GRAPH.md").read_text()
start, end = md.index("<!-- graph:start -->"), md.index("<!-- graph:end -->")
md = md[:start] + "<!-- graph:start -->\n" + "\n".join(lines) + "\n\n" + "\n".join(rows) + "\n" + md[end:]
(root / "docs/TASK_GRAPH.md").write_text(md)
print("rendered", len(g["tasks"]), "tasks")
