"""
Official test cases TC1-TC4.

Each case carries:
  - name:         short human label
  - expected:     what the brief says should happen
  - invoice_id:   which invoice the case exercises
  - explanation:  free-text narrative of the mechanism and any difference
                  from expected (satisfies the brief's "explain any
                  difference from the expected result" requirement)
"""

CASES = {
    "TC1": {
        "name": "Approved overdue reminder",
        "expected": "sent once with portal record",
        "invoice_id": "INV-001",
        "explanation": (
            "INV-001 is unpaid and 20 days overdue (as of the demo date), so the "
            "planner classifies it as 'firm' tone (TONE_FIRM_DAYS=14). The LLM drafts "
            "the reminder text. The human approves via the CLI prompt. "
            "POST /send-reminder returns a portal_record_id (PRT-xxxxxxxx). "
            "The verifier re-reads GET /sent-reminders?invoice_id=INV-001 and "
            "confirms exactly one record exists, matching the local reminder_log. "
            "The SHA-256 idempotency key (invoice:tone:date) prevents a second send "
            "if the suite is re-run the same day. "
            "Difference from expected: none — one send, one portal record."
        ),
    },
    "TC2": {
        "name": "Invoice paid since last run",
        "expected": "excluded",
        "invoice_id": "INV-004",
        "explanation": (
            "INV-004 has status='paid' in the mock portal (it was unpaid in an earlier "
            "snapshot, hence 'paid since last run'). The planner checks status BEFORE "
            "computing days-overdue or calling the LLM, and returns "
            "action='exclude', reason='status=paid'. No email is drafted, no POST is "
            "issued. If a caller bypasses the planner and hits POST /send-reminder "
            "directly, the portal itself rejects with HTTP 400 'Invoice already paid' — "
            "defense in depth. "
            "Difference from expected: none — the invoice is excluded."
        ),
    },
    "TC3": {
        "name": "Client disputes an amount",
        "expected": "reminders paused for that invoice",
        "invoice_id": "INV-005",
        "explanation": (
            "INV-005 has status='disputed'. The planner returns action='exclude', "
            "reason='status=disputed' before any LLM call. The portal additionally "
            "rejects a direct POST /send-reminder with HTTP 400 'Invoice is disputed; "
            "reminders paused'. Because disputed invoices often involve a legitimate "
            "billing question, pausing is the correct business behavior — an automated "
            "'pay now' notice could escalate the dispute. "
            "Difference from expected: none — reminders are paused."
        ),
    },
    "TC4": {
        "name": "Send times out",
        "expected": "sent history checked before retry",
        "invoice_id": "INV-003",
        "explanation": (
            "The mock portal records the reminder in SENT_REMINDERS BEFORE responding, "
            "then sleeps 10s (simulating a slow downstream). The agent's HTTP client "
            "times out at 5s, so the first attempt returns status='timeout' and the "
            "agent does NOT immediately retry. Instead it calls "
            "GET /sent-reminders?invoice_id=INV-003. If a record exists, the send "
            "already happened and the agent skips the retry — preventing a duplicate "
            "email. A naive implementation would retry on timeout and send twice; this "
            "implementation does not. "
            "Difference from expected: none — the sent history is checked before any "
            "retry decision. The 'difference' is behavioral: a naive retry would "
            "produce a duplicate; this code produces zero duplicates."
        ),
    },
}