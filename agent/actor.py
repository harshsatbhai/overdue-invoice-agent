"""
Step 04 — Take action.
Dashboard-only approval. Never prompts in the terminal.
"""
import requests
import hashlib
from datetime import datetime
from config import Config
from database import (
    save_audit, approve_audit, mark_audit_result,
    get_audit_by_key, log_reminder, get_conn,
)


def _pending_key(invoice_id: str, tone: str) -> str:
    return hashlib.sha256(f"pending:{invoice_id}:{tone}".encode()).hexdigest()[:16]


def _send_key(invoice_id: str, tone: str) -> str:
    return hashlib.sha256(
        f"send:{invoice_id}:{tone}:{datetime.utcnow().strftime('%Y-%m-%d')}".encode()
    ).hexdigest()[:16]


def send_reminder_with_approval(invoice_id: str, tone: str,
                                subject: str, body: str,
                                to_email: str) -> dict:
    send_k = _send_key(invoice_id, tone)
    pend_k = _pending_key(invoice_id, tone)

    sent_row = get_audit_by_key(send_k)
    if sent_row and sent_row.get("result") == "sent":
        return {
            "status": "skipped_duplicate",
            "reason": "already sent today",
            "portal_record_id": None,
        }

    pend_row = get_audit_by_key(pend_k)
    if pend_row and pend_row.get("result") == "rejected_by_human":
        return {
            "status": "rejected",
            "reason": "previously rejected via dashboard",
            "portal_record_id": None,
        }

    payload = {
        "invoice_id": invoice_id, "to_email": to_email,
        "subject": subject, "body": body, "tone": tone,
    }

    if not pend_row:
        save_audit(invoice_id, "send_reminder", payload, pend_k)
        pend_row = get_audit_by_key(pend_k)

    if not pend_row or pend_row.get("approved") != 1:
        return {
            "status": "needs_approval",
            "audit_id": pend_row["id"] if pend_row else None,
            "reason": "awaiting approval on /dashboard",
            "portal_record_id": None,
        }

    try:
        resp = requests.post(
            f"{Config.PORTAL_BASE_URL}/send-reminder",
            json={
                "invoice_id": invoice_id, "to_email": to_email,
                "subject": subject, "body": body,
            },
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        portal_record_id = data["portal_record_id"]

        log_reminder({
            "invoice_id": invoice_id, "tone": tone,
            "email_subject": subject, "email_body": body,
            "sent_at": datetime.utcnow().isoformat(),
            "portal_record_id": portal_record_id,
            "status": "sent",
            "approved_at": datetime.utcnow().isoformat(),
        })
        mark_audit_result(pend_row["id"], "sent")
        save_audit(invoice_id, "send_reminder", payload, send_k)
        sent_row = get_audit_by_key(send_k)
        if sent_row:
            mark_audit_result(sent_row["id"], "sent")

        return {"status": "sent", "portal_record_id": portal_record_id}

    except requests.Timeout:
        mark_audit_result(pend_row["id"], "timeout_pending_verification")
        return {
            "status": "timeout",
            "reason": "request timed out; sent history must be checked before retry",
            "portal_record_id": None,
        }
    except requests.HTTPError as e:
        mark_audit_result(pend_row["id"], f"http_error:{e.response.status_code}")
        return {"status": "failed", "reason": str(e), "portal_record_id": None}


# ------------------------------------------------------------------
# Canned templates — used by redraft_all_pending for instant drafts
# ------------------------------------------------------------------
_TEMPLATES = {
    "friendly": (
        "Friendly reminder: Invoice {inv}",
        (
            "Dear {name},\n\n"
            "I hope this message finds you well. I'm writing to gently follow up on "
            "Invoice {inv} for {amt}, which was originally due on {due} and is now "
            "{days} day(s) overdue.\n\n"
            "If the invoice has simply slipped through the cracks, could you please "
            "arrange payment at your earliest convenience? If you need a copy of the "
            "invoice or have any questions about the amount, just let me know and "
            "I'll be happy to help.\n\n"
            "If payment has already been made, please disregard this note and accept "
            "my thanks.\n\n"
            "Best regards,\n[Your Name]\n[Your Freelance Business]"
        ),
    ),
    "firm": (
        "Payment overdue: Invoice {inv}",
        (
            "Dear {name},\n\n"
            "I'm writing to follow up on Invoice {inv} for {amt}, which was due on "
            "{due} and is now {days} days overdue.\n\n"
            "Could you please arrange payment in full by the end of this week? If "
            "there's anything preventing payment, I'd appreciate a quick note so we "
            "can sort it out together.\n\n"
            "Please let me know if you need a copy of the invoice or have any "
            "questions about the amount.\n\n"
            "Thank you for your prompt attention to this matter.\n\n"
            "Best regards,\n[Your Name]\n[Your Freelance Business]"
        ),
    ),
    "final_notice": (
        "Final notice: Invoice {inv}",
        (
            "Dear {name},\n\n"
            "This is a formal notice regarding Invoice {inv} for {amt}, which was "
            "due on {due} and is now {days} days overdue.\n\n"
            "Despite previous reminders, the balance remains outstanding. I kindly "
            "request that payment be made in full within the next seven days. If "
            "payment is not received by then, I may need to consider further steps "
            "to recover the amount owed.\n\n"
            "I'd much prefer to resolve this directly. If you're experiencing "
            "difficulties or believe there's a discrepancy, please contact me so we "
            "can discuss a way forward.\n\n"
            "Thank you for your immediate attention.\n\n"
            "Best regards,\n[Your Name]\n[Your Freelance Business]"
        ),
    ),
}


def _render_template(tone: str, inv: dict, days_overdue: int) -> dict:
    tmpl = _TEMPLATES.get(tone, _TEMPLATES["friendly"])
    fmt = {
        "inv": inv["id"],
        "name": inv["client_name"],
        "amt": f"{inv['currency']} {inv['amount']:.2f}",
        "due": inv["due_date"],
        "days": days_overdue,
    }
    return {
        "subject": tmpl[0].format(**fmt),
        "body": tmpl[1].format(**fmt),
    }


def redraft_all_pending() -> dict:
    """Recreate pending approvals for 3 invoices, one per tone.
    Fast — uses canned templates, no LLM calls."""
    from agent.collector import collect_overdue_invoices
    from agent.planner import plan_actions, compute_days_overdue

    # Clear existing pending rows (approved=0, result NULL)
    conn = get_conn()
    conn.execute(
        "DELETE FROM action_audit WHERE approved=0 AND (result IS NULL OR result='')"
    )
    conn.commit()
    conn.close()

    invoices = collect_overdue_invoices()

    # Find one eligible invoice per tone
    picks = []  # (inv, tone, days_overdue)
    for desired in ("friendly", "firm", "final_notice"):
        for inv in invoices:
            if inv["status"] in ("paid", "disputed"):
                continue
            days = compute_days_overdue(inv["due_date"])
            if days <= 0:
                continue
            # Skip if already sent today
            send_k = _send_key(inv["id"], desired)
            existing = get_audit_by_key(send_k)
            if existing and existing.get("result") == "sent":
                continue
            # Skip if already picked
            if any(p[0]["id"] == inv["id"] for p in picks):
                continue
            picks.append((inv, desired, days))
            break

    # If we didn't get all 3 (not enough invoices), fill with remaining unpaid
    if len(picks) < 3:
        for inv in invoices:
            if inv["status"] in ("paid", "disputed"):
                continue
            if any(p[0]["id"] == inv["id"] for p in picks):
                continue
            days = compute_days_overdue(inv["due_date"])
            if days <= 0:
                continue
            # Pick tone from days
            if days >= 30:
                tone = "final_notice"
            elif days >= 14:
                tone = "firm"
            else:
                tone = "friendly"
            picks.append((inv, tone, days))
            if len(picks) >= 3:
                break

    created = 0
    for inv, tone, days in picks:
        email = _render_template(tone, inv, days)
        result = send_reminder_with_approval(
            inv["id"], tone, email["subject"], email["body"],
            inv["client_email"],
        )
        if result["status"] == "needs_approval":
            created += 1

    return {"created": created}