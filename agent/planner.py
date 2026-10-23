from datetime import datetime, date
from config import Config

def compute_days_overdue(due_date_str: str) -> int:
    due = datetime.strptime(due_date_str, "%Y-%m-%d").date()
    return (date.today() - due).days

def decide_tone(days_overdue: int) -> str:
    if days_overdue >= Config.TONE_FINAL_DAYS:
        return "final_notice"
    elif days_overdue >= Config.TONE_FIRM_DAYS:
        return "firm"
    elif days_overdue >= Config.TONE_FRIENDLY_DAYS:
        return "friendly"
    return None  # not yet overdue enough for a reminder? (still chase if >0)

def plan_actions(invoices: list[dict]) -> list[dict]:
    """Step 02: Apply deterministic rules.
    Excludes paid/disputed. Escalates tone by days overdue."""
    plans = []
    for inv in invoices:
        # RULE: exclude paid and disputed
        if inv["status"] in ("paid", "disputed"):
            plans.append({
                "invoice_id": inv["id"],
                "action": "exclude",
                "reason": f"status={inv['status']}",
                "days_overdue": None,
                "tone": None,
            })
            continue

        days = compute_days_overdue(inv["due_date"])
        if days <= 0:
            plans.append({
                "invoice_id": inv["id"],
                "action": "skip",
                "reason": "not yet overdue",
                "days_overdue": days,
                "tone": None,
            })
            continue

        tone = decide_tone(days)
        if tone is None:
            # Very early overdue: still send friendly if >=1 day
            tone = "friendly"

        plans.append({
            "invoice_id": inv["id"],
            "action": "send_reminder",
            "reason": f"{days} days overdue → {tone}",
            "days_overdue": days,
            "tone": tone,
        })
    return plans