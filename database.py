import sqlite3
import json
from datetime import datetime
from config import Config

def get_conn():
    conn = sqlite3.connect(Config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS invoices (id TEXT PRIMARY KEY, client_name TEXT, client_email TEXT, amount REAL, currency TEXT, due_date TEXT, status TEXT DEFAULT 'unpaid', portal_invoice_id TEXT, last_synced_at TEXT);
        CREATE TABLE IF NOT EXISTS reminder_log (id INTEGER PRIMARY KEY AUTOINCREMENT, invoice_id TEXT, tone TEXT, email_subject TEXT, email_body TEXT, sent_at TEXT, portal_record_id TEXT, status TEXT, approved_at TEXT, promise_to_pay_date TEXT, notes TEXT);
        CREATE TABLE IF NOT EXISTS action_audit (id INTEGER PRIMARY KEY AUTOINCREMENT, invoice_id TEXT, action_type TEXT, proposed_payload TEXT, approved INTEGER DEFAULT 0, executed_at TEXT, result TEXT, idempotency_key TEXT UNIQUE);
        CREATE TABLE IF NOT EXISTS test_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, tc_id TEXT, input_json TEXT, expected TEXT, actual TEXT, evidence_json TEXT, passed INTEGER, notes TEXT, run_at TEXT);
    """)
    conn.commit()
    conn.close()

def upsert_invoice(inv: dict):
    conn = get_conn()
    conn.execute("""
        INSERT INTO invoices (id, client_name, client_email, amount, currency, due_date, status, portal_invoice_id, last_synced_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET client_name=excluded.client_name, client_email=excluded.client_email, amount=excluded.amount, due_date=excluded.due_date, status=excluded.status, last_synced_at=excluded.last_synced_at
    """, (inv["id"], inv["client_name"], inv["client_email"], inv["amount"], inv["currency"], inv["due_date"], inv.get("status", "unpaid"), inv.get("portal_invoice_id"), datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()

def get_invoice(invoice_id: str):
    conn = get_conn()
    row = conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def get_all_invoices():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM invoices").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def log_reminder(entry: dict) -> int:
    conn = get_conn()
    cur = conn.execute("""
        INSERT INTO reminder_log (invoice_id, tone, email_subject, email_body, sent_at, portal_record_id, status, approved_at, promise_to_pay_date, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (entry["invoice_id"], entry["tone"], entry["email_subject"], entry["email_body"], entry.get("sent_at"), entry.get("portal_record_id"), entry.get("status", "pending"), entry.get("approved_at"), entry.get("promise_to_pay_date"), entry.get("notes")))
    conn.commit()
    rid = cur.lastrowid
    conn.close()
    return rid

def get_reminder_log():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM reminder_log ORDER BY id DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_still_unpaid_total() -> float:
    conn = get_conn()
    row = conn.execute("SELECT COALESCE(SUM(amount), 0) as total FROM invoices WHERE status='unpaid'").fetchone()
    conn.close()
    return row["total"]

def save_audit(invoice_id: str, action_type: str, payload: dict, idempotency_key: str) -> int:
    conn = get_conn()
    cur = conn.execute("INSERT OR IGNORE INTO action_audit (invoice_id, action_type, proposed_payload, idempotency_key) VALUES (?, ?, ?, ?)", (invoice_id, action_type, json.dumps(payload), idempotency_key))
    conn.commit()
    aid = cur.lastrowid
    conn.close()
    return aid

def approve_audit(audit_id: int):
    conn = get_conn()
    conn.execute("UPDATE action_audit SET approved=1, executed_at=? WHERE id=?", (datetime.utcnow().isoformat(), audit_id))
    conn.commit()
    conn.close()

def mark_audit_result(audit_id: int, result: str):
    conn = get_conn()
    conn.execute("UPDATE action_audit SET result=? WHERE id=?", (result, audit_id))
    conn.commit()
    conn.close()

def get_audit_by_key(key: str):
    conn = get_conn()
    row = conn.execute("SELECT * FROM action_audit WHERE idempotency_key=?", (key,)).fetchone()
    conn.close()
    return dict(row) if row else None

def save_test_run(tc_id: str, input_json: str, expected: str, actual: str, evidence_json: str, passed: bool, notes: str):
    conn = get_conn()
    conn.execute("INSERT INTO test_runs (tc_id, input_json, expected, actual, evidence_json, passed, notes, run_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (tc_id, input_json, expected, actual, evidence_json, int(passed), notes, datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()

def update_promise(reminder_id: int, promise_date: str, note: str = "") -> dict:
    from datetime import datetime as _dt
    try: parsed = _dt.strptime(promise_date, "%Y-%m-%d").date()
    except ValueError: raise ValueError("promise_date must be YYYY-MM-DD")
    
    conn = get_conn()
    row = conn.execute("SELECT * FROM reminder_log WHERE id=?", (reminder_id,)).fetchone()
    if not row:
        conn.close()
        raise ValueError(f"reminder {reminder_id} not found")

    ts = _dt.utcnow().isoformat()
    suffix = f" | promise: {promise_date}"
    if note: suffix += f" ({note})"
    new_notes = ((row["notes"] or "") + suffix).strip()

    conn.execute("UPDATE reminder_log SET promise_to_pay_date=?, notes=? WHERE id=?", (promise_date, new_notes, reminder_id))
    conn.commit()
    updated = conn.execute("SELECT * FROM reminder_log WHERE id=?", (reminder_id,)).fetchone()
    conn.close()
    return dict(updated)

def clear_promise(reminder_id: int) -> dict:
    conn = get_conn()
    row = conn.execute("SELECT * FROM reminder_log WHERE id=?", (reminder_id,)).fetchone()
    if not row:
        conn.close()
        raise ValueError(f"reminder {reminder_id} not found")
    if not row["promise_to_pay_date"]:
        conn.close()
        raise ValueError("no promise to clear")

    ts = datetime.utcnow().isoformat()
    new_notes = ((row["notes"] or "") + f" | promise cleared at {ts}").strip()
    conn.execute("UPDATE reminder_log SET promise_to_pay_date=NULL, notes=? WHERE id=?", (new_notes, reminder_id))
    conn.commit()
    updated = conn.execute("SELECT * FROM reminder_log WHERE id=?", (reminder_id,)).fetchone()
    conn.close()
    return dict(updated)

def get_promise_summary() -> dict:
    conn = get_conn()
    rows = conn.execute("""
        SELECT r.id, r.invoice_id, r.promise_to_pay_date, i.client_name, i.amount, i.currency, i.status as invoice_status
        FROM reminder_log r LEFT JOIN invoices i ON i.id = r.invoice_id
        WHERE r.promise_to_pay_date IS NOT NULL AND r.promise_to_pay_date != '' ORDER BY r.promise_to_pay_date ASC
    """).fetchall()
    conn.close()

    from datetime import date as _date
    today = _date.today()
    items = []
    for r in rows:
        d = r["promise_to_pay_date"]
        try: days_until = (_date.fromisoformat(d) - today).days
        except Exception: days_until = None
        items.append({"reminder_id": r["id"], "invoice_id": r["invoice_id"], "client_name": r["client_name"], "amount": r["amount"], "currency": r["currency"], "invoice_status": r["invoice_status"], "promise_to_pay_date": d, "days_until": days_until, "overdue_promise": days_until is not None and days_until < 0})

    return {"items": items, "count": len(items), "overdue_promises": [x for x in items if x["overdue_promise"]]}

def get_latest_sent_reminder_id(invoice_id: str):
    """Helper for promise sync: finds the most recent sent reminder without a promise."""
    conn = get_conn()
    row = conn.execute("SELECT id FROM reminder_log WHERE invoice_id=? AND status='sent' AND promise_to_pay_date IS NULL ORDER BY id DESC LIMIT 1", (invoice_id,)).fetchone()
    conn.close()
    return row["id"] if row else None