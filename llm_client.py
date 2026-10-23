import requests
import json
from datetime import datetime
from config import Config

def call_nemotron(system_prompt: str, user_prompt: str, temperature: float = 0.3, max_tokens: int = 1024) -> str:
    if not Config.LLM_API_KEY:
        raise RuntimeError("No LLM API key.")
    headers = {"Authorization": f"Bearer {Config.LLM_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": Config.LLM_MODEL, "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}], "temperature": temperature, "max_tokens": max_tokens}
    resp = requests.post(f"{Config.LLM_BASE_URL}/chat/completions", headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]

def generate_reminder_email(client_name: str, invoice_id: str, amount: float, currency: str, due_date: str, days_overdue: int, tone: str) -> dict:
    system = "You are a professional accounts-receivable assistant writing on behalf of a freelancer. You write complete, well-structured business emails. Every email you write MUST have:\n  1. A greeting line\n  2. An opening sentence stating the purpose\n  3. At least one sentence with the invoice details\n  4. A clear request or next step\n  5. A polite closing line\n  6. A sign-off\n\nThe body MUST be at least 4 sentences and formatted as multiple short paragraphs separated by blank lines. NEVER write a one-line or single-paragraph email. Return ONLY valid JSON with keys 'subject' and 'body'."
    user = f"""Draft a {tone} payment reminder email.
Client: {client_name}
Invoice: {invoice_id}
Amount: {currency} {amount:.2f}
Due date: {due_date}
Days overdue: {days_overdue}

Return JSON: {{"subject": "...", "body": "..."}}"""

    raw = call_nemotron(system, user, max_tokens=1024)
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError(f"LLM did not return JSON: {raw[:200]}")
    parsed = json.loads(raw[start:end])
    subject = parsed.get("subject", f"Payment reminder: {invoice_id}")
    body = parsed.get("body", "").strip()

    if len(body) < 180 or body.count("\n") < 1:
        body = f"Dear {client_name},\n\nI'm writing to follow up on Invoice {invoice_id} for {currency} {amount:.2f}, which was due on {due_date} and is now {days_overdue} day(s) overdue.\n\nCould you please arrange payment at your earliest convenience?\n\nBest regards,\n[Your Name]"

    return {"subject": subject, "body": body}

def extract_promise_date(client_message: str) -> str:
    """Use LLM to extract a YYYY-MM-DD date from a client's reply."""
    system = "You are a data extraction bot. Extract the promised payment date from the client's message. Return ONLY the date in YYYY-MM-DD format. If no date is found, return 'NONE'."
    user = f"Client message: '{client_message}'\nToday's date is {datetime.utcnow().strftime('%Y-%m-%d')}."
    
    try:
        raw = call_nemotron(system, user, temperature=0.0, max_tokens=20).strip()
        if "NONE" in raw.upper(): return None
        import re
        match = re.search(r'\d{4}-\d{2}-\d{2}', raw)
        return match.group(0) if match else None
    except Exception as e:
        print(f"  [LLM extraction error: {e}]")
        return None