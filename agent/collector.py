import requests
from config import Config
from database import upsert_invoice, get_all_invoices

def collect_overdue_invoices() -> list[dict]:
    """Step 01: Fetch invoices from the mock portal and persist them."""
    resp = requests.get(f"{Config.PORTAL_BASE_URL}/invoices", timeout=10)
    resp.raise_for_status()
    invoices = resp.json()["invoices"]

    for inv in invoices:
        upsert_invoice({
            "id": inv["id"],
            "client_name": inv["client_name"],
            "client_email": inv["client_email"],
            "amount": inv["amount"],
            "currency": inv["currency"],
            "due_date": inv["due_date"],
            "status": inv["status"],
            "portal_invoice_id": inv["id"],
        })

    return get_all_invoices()