from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import datetime, timedelta
import uuid
import random

from ui.web_routes import router as dashboard_router


def _trim_reminder_log(keep: int = 5) -> dict:
    try:
        from database import get_conn, init_db
        init_db()
        conn = get_conn()
        before = conn.execute("SELECT COUNT(*) AS n FROM reminder_log").fetchone()["n"]
        conn.execute("""
            DELETE FROM reminder_log
            WHERE id NOT IN (SELECT id FROM reminder_log ORDER BY id DESC LIMIT ?)
        """, (keep,))
        conn.commit()
        after = conn.execute("SELECT COUNT(*) AS n FROM reminder_log").fetchone()["n"]
        conn.close()
        return {"before": before, "after": after, "deleted": before - after}
    except Exception as e:
        return {"error": str(e)}


app = FastAPI(title="InvoiceChase Mock Billing Portal")
app.include_router(dashboard_router)


@app.on_event("startup")
def _on_startup():
    result = _trim_reminder_log(keep=5)
    if "error" not in result:
        print(f"[startup] reminder_log trimmed: {result['before']} → {result['after']} rows")

    try:
        from database import get_conn
        conn = get_conn()
        n = conn.execute("""
            DELETE FROM action_audit WHERE approved=1 AND (result IS NULL OR result='')
        """).rowcount
        conn.commit()
        conn.close()
        print(f"[startup] cleared {n} approved-but-unsent ghost row(s)")
    except Exception as e:
        print(f"[startup] ghost-row cleanup FAILED: {e}")


INVOICES = {
    "INV-001": {"id": "INV-001", "client_name": "Acme Corp", "client_email": "billing@acme.example", "amount": 4500.00, "currency": "USD", "due_date": (datetime.utcnow() - timedelta(days=20)).strftime("%Y-%m-%d"), "status": "unpaid"},
    "INV-002": {"id": "INV-002", "client_name": "Beta LLC", "client_email": "accounts@beta.example", "amount": 1200.00, "currency": "USD", "due_date": (datetime.utcnow() - timedelta(days=5)).strftime("%Y-%m-%d"), "status": "unpaid"},
    "INV-003": {"id": "INV-003", "client_name": "Gamma Inc", "client_email": "ap@gamma.example", "amount": 800.00, "currency": "USD", "due_date": (datetime.utcnow() - timedelta(days=40)).strftime("%Y-%m-%d"), "status": "unpaid"},
    "INV-004": {"id": "INV-004", "client_name": "Delta Co", "client_email": "pay@delta.example", "amount": 3000.00, "currency": "USD", "due_date": (datetime.utcnow() - timedelta(days=25)).strftime("%Y-%m-%d"), "status": "paid"},
    "INV-005": {"id": "INV-005", "client_name": "Epsilon Ltd", "client_email": "finance@epsilon.example", "amount": 2200.00, "currency": "USD", "due_date": (datetime.utcnow() - timedelta(days=15)).strftime("%Y-%m-%d"), "status": "disputed"}
}

SENT_REMINDERS = []
CLIENT_REPLIES = {}


class ReminderRequest(BaseModel):
    invoice_id: str
    to_email: str
    subject: str
    body: str


class ReplyRequest(BaseModel):
    invoice_id: str
    message: str


@app.get("/invoices")
def list_invoices():
    return {"invoices": list(INVOICES.values())}


@app.get("/invoices/{invoice_id}")
def get_invoice(invoice_id: str):
    inv = INVOICES.get(invoice_id)
    if not inv: raise HTTPException(404, "Invoice not found")
    return inv


@app.post("/send-reminder")
def send_reminder(req: ReminderRequest):
    inv = INVOICES.get(req.invoice_id)
    if not inv: raise HTTPException(404, "Invoice not found")
    if inv["status"] == "paid": raise HTTPException(400, "Invoice already paid")
    if inv["status"] == "disputed": raise HTTPException(400, "Invoice is disputed; reminders paused")

    record_id = f"PRT-{uuid.uuid4().hex[:8]}"
    SENT_REMINDERS.append({"portal_record_id": record_id, "invoice_id": req.invoice_id, "to_email": req.to_email, "subject": req.subject, "body": req.body, "sent_at": datetime.utcnow().isoformat()})

    if req.invoice_id == "INV-003" and random.random() < 0.6:
        import time
        time.sleep(10)

    return {"portal_record_id": record_id, "status": "sent"}


@app.get("/sent-reminders")
def sent_reminders(invoice_id: str | None = None):
    if invoice_id:
        return {"sent": [r for r in SENT_REMINDERS if r["invoice_id"] == invoice_id]}
    return {"sent": SENT_REMINDERS}


# --- Simulated Inbox ---
@app.post("/simulate-client-reply")
def simulate_reply(req: ReplyRequest):
    """Record a simulated client reply, then immediately run promise
    extraction so the result is visible in the response."""
    CLIENT_REPLIES[req.invoice_id] = req.message

    extraction = {"ran": False, "promise_date": None, "promise_display": None, "error": None}
    try:
        from agent.promise_sync import sync_promises
        from database import get_promise_summary
        sync_promises()
        summary = get_promise_summary()
        match = next((p for p in summary["items"] if p["invoice_id"] == req.invoice_id), None)
        extraction = {
            "ran": True,
            "promise_date": match["promise_to_pay_date"] if match else None,      # ISO
            "promise_display": match["promise_display"] if match else None,      # dd-mm-yyyy
            "error": None if match else "no promise extracted (see server logs for raw LLM response)",
        }
    except Exception as e:
        extraction = {"ran": True, "promise_date": None, "promise_display": None, "error": str(e)}

    return {
        "status": "reply received",
        "invoice_id": req.invoice_id,
        "extraction": extraction,
    }


@app.get("/client-replies")
def get_replies():
    return CLIENT_REPLIES


@app.get("/health")
def health():
    return {"status": "ok"}