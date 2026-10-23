from database import get_reminder_log, get_still_unpaid_total, get_all_invoices

def show_results():
    """Step 06: Result view — reminder log, promised dates, still-unpaid total."""
    print("\n" + "=" * 60)
    print("REMINDER LOG")
    print("=" * 60)
    log = get_reminder_log()
    if not log:
        print("(no reminders sent yet)")
    for r in log:
        print(f"  [{r['sent_at']}] {r['invoice_id']} | {r['tone']} | "
              f"portal={r['portal_record_id']} | status={r['status']}")
        if r.get("promise_to_pay_date"):
            print(f"    → Promise to pay: {r['promise_to_pay_date']}")

    print("\n" + "=" * 60)
    print("STILL-UNPAID TOTAL")
    print("=" * 60)
    total = get_still_unpaid_total()
    print(f"  ${total:,.2f}")

    print("\n" + "=" * 60)
    print("INVOICE STATES")
    print("=" * 60)
    for inv in get_all_invoices():
        print(f"  {inv['id']}: {inv['client_name']} | "
              f"{inv['currency']} {inv['amount']:,.2f} | "
              f"status={inv['status']} | due={inv['due_date']}")