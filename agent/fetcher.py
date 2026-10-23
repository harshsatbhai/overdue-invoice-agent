import requests
from config import Config

def verify_invoice_state(invoice_id: str) -> dict:
    """Step 03: Re-fetch the invoice from the portal to confirm current state
    (e.g., it hasn't been paid since our DB snapshot)."""
    resp = requests.get(
        f"{Config.PORTAL_BASE_URL}/invoices/{invoice_id}", timeout=10
    )
    if resp.status_code == 404:
        return {"invoice_id": invoice_id, "exists": False, "status": None}
    resp.raise_for_status()
    inv = resp.json()
    return {
        "invoice_id": invoice_id,
        "exists": True,
        "status": inv["status"],
        "amount": inv["amount"],
        "client_email": inv["client_email"],
        "client_name": inv["client_name"],
    }

def fetch_sent_history(invoice_id: str) -> list[dict]:
    """For TC4: check whether a reminder was already sent for this invoice."""
    resp = requests.get(
        f"{Config.PORTAL_BASE_URL}/sent-reminders",
        params={"invoice_id": invoice_id}, timeout=10
    )
    resp.raise_for_status()
    return resp.json()["sent"]