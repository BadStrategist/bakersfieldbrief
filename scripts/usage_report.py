"""Pull real token/cost usage from the Hermes session DB (last 48h)."""
import sqlite3
import time

db = r"C:\Users\tscac\AppData\Local\hermes\state.db"
c = sqlite3.connect(db)
c.row_factory = sqlite3.Row

cutoff = time.time() - 48 * 3600
try:
    rows = c.execute(
        """SELECT session_id, model, SUM(input_tokens) AS tin,
                  SUM(output_tokens) AS tout, SUM(estimated_cost_usd) AS cost,
                  SUM(api_call_count) AS calls
           FROM session_model_usage
           WHERE last_seen >= ?
           GROUP BY session_id, model
           ORDER BY cost DESC""", (cutoff,)).fetchall()
    total = 0.0
    print(f"{'session':<42}{'model':<30}{'in_tok':>9}{'out_tok':>9}{'cost$':>9}{'calls':>6}")
    for r in rows:
        cost = r["cost"] or 0.0
        total += cost
        sid = (r["session_id"] or "")[:40]
        print(f"{sid:<42}{(r['model'] or '')[:28]:<30}{r['tin'] or 0:>9}{r['tout'] or 0:>9}{cost:>9.4f}{r['calls'] or 0:>6}")
    print("-" * 105)
    print(f"TOTAL 48h: ${total:.4f}  (per-day ≈ ${total/2:.4f})")
    # per-model totals
    print("\nby model:")
    for r in c.execute(
            """SELECT model, SUM(input_tokens) tin, SUM(output_tokens) tout,
                      SUM(estimated_cost_usd) cost, SUM(api_call_count) calls
               FROM session_model_usage WHERE last_seen >= ?
               GROUP BY model ORDER BY cost DESC""", (cutoff,)).fetchall():
        print(f"  {(r['model'] or '?')[:40]:<42}{r['tin'] or 0:>10}{r['tout'] or 0:>10}"
              f"${r['cost'] or 0:>9.4f}{r['calls'] or 0:>6}")
except sqlite3.Error as e:
    print("ERR:", e)
    cols = [r[1] for r in c.execute("PRAGMA table_info(session_model_usage)").fetchall()]
    print("columns:", cols)
