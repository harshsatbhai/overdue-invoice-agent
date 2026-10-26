import requests
import json
import re
import logging
from datetime import datetime
from config import Config

log = logging.getLogger("llm_client")


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
    """Use LLM to extract a YYYY-MM-DD date from a client's reply.

    Returns None only if the model explicitly says NONE, or if extraction
    fails after retries. Logs the raw LLM response on every attempt so
    failures are diagnosable.
    """
    system = (
        "You are a data extraction bot. Extract the promised payment date "
        "from the client's message. Today's date is provided for reference. "
        "Return ONLY the date in YYYY-MM-DD format, with no other text. "
        "If the client gives a relative date (e.g. 'next Friday', 'in two weeks', "
        "'the 15th'), resolve it against today's date. "
        "If no payment date is mentioned, return exactly: NONE"
    )
    today = datetime.utcnow().strftime("%Y-%m-%d")
    user = f"Today's date: {today}\nClient message: '{client_message}'"

    for attempt in range(2):
        try:
            raw = call_nemotron(system, user, temperature=0.0, max_tokens=64)
            log.warning("extract_promise_date raw (attempt %d): %r", attempt + 1, raw)
            print(f"  [LLM extract] raw response (attempt {attempt + 1}): {raw!r}")
        except Exception as e:
            log.warning("extract_promise_date LLM error (attempt %d): %s", attempt + 1, e)
            print(f"  [LLM extract error (attempt {attempt + 1}): {e}]")
            continue

        text = raw.strip()
        # Strip markdown fences if the model wraps its answer
        text = re.sub(r'^```[a-zA-Z]*\s*|\s*```$', '', text).strip()

        # Explicit NONE — check as a whole token, not a substring
        if re.fullmatch(r'NONE\.?', text, flags=re.IGNORECASE):
            log.warning("extract_promise_date: model returned NONE for message %r", client_message)
            print(f"  [LLM extract] model explicitly returned NONE")
            return None

        # Look for ISO date anywhere in the response
        match = re.search(r'\b(\d{4})-(\d{2})-(\d{2})\b', text)
        if match:
            candidate = match.group(0)
            try:
                datetime.strptime(candidate, "%Y-%m-%d")
                log.warning("extract_promise_date: extracted %s from %r", candidate, client_message)
                print(f"  [LLM extract] parsed date: {candidate}")
                return candidate
            except ValueError:
                log.warning("extract_promise_date: invalid date %r in raw %r", candidate, raw)
                print(f"  [LLM extract] invalid date value: {candidate}")

        log.warning("extract_promise_date: no ISO date found in raw %r (attempt %d)", raw, attempt + 1)
        print(f"  [LLM extract] no ISO date found in response (attempt {attempt + 1})")

    return None