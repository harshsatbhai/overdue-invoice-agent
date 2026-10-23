import requests
from config import Config
from database import get_reminder_log

def verify_sent_status(invoice_id: str) -> dict:
    """Step 05: Independently check the portal's sent history and invoice state."""
    sent = requests.get(
        f"{Config.PORTAL_BASE_URL}/sent-reminders",
        params={"invoice_id": invoice_id}, timeout=10
    ).json()["sent"]

    inv = requests.get(
        f"{Config.PORTAL_BASE_URL}/invoices/{invoice_id}", timeout=10
    ).json()

    local_log = [r for r in get_reminder_log() if r["invoice_id"] == invoice_id]

    return {
        "invoice_id": invoice_id,
        "portal_sent_count": len(sent),
        "portal_records": sent,
        "local_log_count": len(local_log),
        "invoice_payment_status": inv["status"],
        "consistent": len(sent) == len(local_log),
    }