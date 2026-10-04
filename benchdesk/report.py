from collections import Counter
from html import escape
from statistics import mean


def totals(run):
    return Counter(row["outcome"] for row in run["results"])


def comparison(current, previous):
    if not previous:
        return "No comparable previous run (same suite configuration and host)."
    old = {(r["check_id"], r["iteration"]): r for r in previous["results"]}
    regressions = recoveries = 0
    for row in current["results"]:
        before = old.get((row["check_id"], row["iteration"]))
        if before and row["outcome"] != "CANCELLED":
            regressions += before["outcome"] == "PASS" and row["outcome"] != "PASS"
            recoveries += before["outcome"] != "PASS" and row["outcome"] == "PASS"
    return (
        f"Compared with previous matching run: {regressions} regressions, {recoveries} recoveries."
    )


def render_html(run, previous=None):
    counts = totals(run)
    elapsed = [r["elapsed_ms"] for r in run["results"]]
    rows = []
    for row in run["results"]:
        values = [
            row["iteration"],
            row["name"],
            row["method"],
            row["path"],
            row["outcome"],
            row["status"] if row["status"] is not None else "—",
            row["elapsed_ms"],
            row["reason"],
        ]
        rows.append("<tr>" + "".join(f"<td>{escape(str(v))}</td>" for v in values) + "</tr>")
    average = f"{mean(elapsed):.1f}" if elapsed else "0.0"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy"
content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'">
<title>BenchDesk report</title><style>
body {{font:15px/1.6 system-ui;background:#f4f6fa;color:#203047;padding:24px}}
main {{max-width:1200px;margin:auto}} table {{border-collapse:collapse;width:100%;background:white}}
td,th {{text-align:left;border-bottom:1px solid #ddd;padding:10px;overflow-wrap:anywhere}}
.summary {{background:white;padding:16px;border-left:4px solid #2469ac}} .scroll {{overflow-x:auto}}
</style></head><body><main><h1>BenchDesk · {escape(run["suite_name"])}</h1>
<p>{escape(run["started_at"])} · {escape(run["base_url"])}</p>
<p class="summary">PASS {counts["PASS"]} · FAIL {counts["FAIL"]} · ERROR {counts["ERROR"]}
· CANCELLED {counts["CANCELLED"]} · {len(run["results"])}/{run["planned"]} attempted
· Mean elapsed {average} ms · Run cancelled: {run["cancelled"]}</p>
<p>{escape(comparison(run, previous))}</p><div class="scroll"><table><thead><tr>
<th>Round</th><th>Check</th><th>Method</th><th>Path</th><th>Outcome</th><th>HTTP</th><th>ms</th><th>Reason</th>
</tr></thead><tbody>{"".join(rows)}</tbody></table></div>
<p>Query strings, headers, request bodies and response bodies are omitted. Names, hosts and paths
can still be private. Keep reports private. Timings include local client overhead;
this is not a load test.</p>
</main></body></html>"""
