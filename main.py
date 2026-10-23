"""
Main CLI for the Overdue Invoice Follow-up Agent.
Usage:
  python main.py collect      # Step 01
  python main.py plan         # Step 02 (dry plan)
  python main.py run          # Steps 01-04 with approval
  python main.py verify       # Step 05 for last sent reminders
  python main.py results      # Step 06 result view
"""
import sys
from database import init_db
from agent.collector import collect_overdue_invoices
from agent.planner import plan_actions
from agent.actor import send_reminder_with_approval
from agent.verifier import verify_sent_status
from ui.result_view import show_results
from llm_client import generate_reminder_email

def main():
    init_db()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"

    if cmd == "collect":
        invs = collect_overdue_invoices()
        print(f"Collected {len(invs)} invoices.")
        for i in invs:
            print(f"  {i['id']}: {i['status']}")

    elif cmd == "plan":
        invs = collect_overdue_invoices()
        plans = plan_actions(invs)
        for p in plans:
            print(f"{p['invoice_id']}: {p['action']} — {p['reason']}")

    elif cmd == "run":
        invs = collect_overdue_invoices()
        plans = plan_actions(invs)
        for p in plans:
            if p["action"] != "send_reminder":
                print(f"SKIP {p['invoice_id']}: {p['reason']}")
                continue
            inv = next(i for i in invs if i["id"] == p["invoice_id"])
            email = generate_reminder_email(
                inv["client_name"], inv["id"], inv["amount"],
                inv["currency"], inv["due_date"],
                p["days_overdue"], p["tone"]
            )
            result = send_reminder_with_approval(
                inv["id"], p["tone"], email["subject"], email["body"],
                inv["client_email"]
            )
            print(f"  {inv['id']}: {result['status']}")

    elif cmd == "verify":
        from database import get_reminder_log
        for r in get_reminder_log():
            v = verify_sent_status(r["invoice_id"])
            print(f"{r['invoice_id']}: {v}")

    elif cmd == "results":
        show_results()

    else:
        print(__doc__)

if __name__ == "__main__":
    main()