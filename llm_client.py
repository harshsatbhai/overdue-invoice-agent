import requests
import json
import re
import logging
from datetime import datetime, date, timedelta
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


# ------------------------------------------------------------------
# Flexible date parsing — accepts many formats the model may emit
# and normalizes to ISO (YYYY-MM-DD). Returns None on failure.
# ------------------------------------------------------------------
_DATE_FORMATS = [
    "%Y-%m-%d",       # 2026-12-24
    "%Y/%m/%d",       # 2026/12/24
    "%d-%m-%Y",       # 24-12-2026
    "%d/%m/%Y",       # 24/12/2026
    "%d.%m.%Y",       # 24.12.2026
    "%d %B %Y",       # 24 December 2026
    "%d %b %Y",       # 24 Dec 2026
    "%B %d, %Y",      # December 24, 2026
    "%b %d, %Y",      # Dec 24, 2026
    "%B %d %Y",       # December 24 2026
    "%b %d %Y",       # Dec 24 2026
    "%d-%B-%Y",       # 24-December-2026
    "%d-%b-%Y",       # 24-Dec-2026
]


def _normalize_date_string(s: str) -> str | None:
    """Try every known format; return ISO date or None."""
    s = s.strip().strip('.,;:').strip()
    if not s:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _parse_model_output(text: str, today: date) -> str | None:
    """Given the model's raw answer, return ISO date or None.

    Handles:
      - Explicit NONE
      - Strict fullmatch (model obeyed)
      - "December 24th" / "24 December" / "Dec 24" (no year → next occurrence)
      - ISO dates anywhere in prose (prefer last match)
      - dd-mm-yyyy / dd/mm/yyyy anywhere
    """
    text = text.strip()
    text = re.sub(r'^```[a-zA-Z]*\s*|\s*```$', '', text).strip()

    if re.fullmatch(r'NONE\.?', text, flags=re.IGNORECASE):
        return None

    # Strict: whole response is a parseable date
    strict = _normalize_date_string(text)
    if strict:
        return strict

    # 1) Try ISO anywhere — prefer last match (model often echoes reference first)
    iso_matches = re.findall(r'\b(\d{4})-(\d{2})-(\d{2})\b', text)
    for y, m, d in reversed(iso_matches):
        try:
            return datetime(int(y), int(m), int(d)).strftime("%Y-%m-%d")
        except ValueError:
            continue

    # 2) dd-mm-yyyy / dd/mm/yyyy anywhere (day-first, non-ISO year at end)
    dmy_matches = re.findall(r'\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b', text)
    for d, m, y in reversed(dmy_matches):
        try:
            return datetime(int(y), int(m), int(d)).strftime("%Y-%m-%d")
        except ValueError:
            continue

    # 3) Natural language: "December 24th", "24 December", "Dec 24", "Dec 24 2026"
    month_names = r'(?:january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)'

    # "December 24th [2026]"
    for m in re.finditer(
        rf'\b({month_names})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s*(\d{{4}}))?\b',
        text, flags=re.IGNORECASE,
    ):
        month_s, day_s, year_s = m.group(1), m.group(2), m.group(3)
        iso = _build_date(month_s, int(day_s), year_s, today)
        if iso:
            return iso

    # "24th [of] December [2026]" or "24 December [2026]"
    for m in re.finditer(
        rf'\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({month_names})\.?(?:,?\s*(\d{{4}}))?\b',
        text, flags=re.IGNORECASE,
    ):
        day_s, month_s, year_s = m.group(1), m.group(2), m.group(3)
        iso = _build_date(month_s, int(day_s), year_s, today)
        if iso:
            return iso

    return None


def _build_date(month_name: str, day: int, year_str: str | None, today: date) -> str | None:
    """Given month name + day + optional year, produce ISO. If no year,
    pick the next occurrence on/after today."""
    month_num = _month_to_num(month_name)
    if not month_num:
        return None
    try:
        if year_str:
            return datetime(int(year_str), month_num, day).strftime("%Y-%m-%d")
        # No year: this year if not yet passed, else next year
        candidate = date(today.year, month_num, day)
        if candidate < today:
            candidate = date(today.year + 1, month_num, day)
        return candidate.strftime("%Y-%m-%d")
    except ValueError:
        return None


_MONTH_MAP = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}


def _month_to_num(name: str) -> int | None:
    return _MONTH_MAP.get(name.strip().lower().rstrip("."))


def extract_promise_date(client_message: str) -> str | None:
    """Use LLM to extract the promised payment date from a client reply.

    Accepts many formats; always returns ISO (YYYY-MM-DD) or None.
    """
    system = (
        "You are a strict data-extraction bot. Read a client's email reply and "
        "extract the date they promise to pay on.\n"
        "Rules:\n"
        "- Understand ALL common date formats: '24 December', 'December 24th', "
        "'Dec 24', '24/12/2026', '24-12-2026', 'next Friday', 'in two weeks', "
        "'end of the month', 'tomorrow', 'the 15th'.\n"
        "- If a month/day is given without a year, use the NEXT occurrence on or "
        "after the reference date.\n"
        "- Resolve relative dates against the reference date.\n"
        "- Return ONLY the date in YYYY-MM-DD format.\n"
        "- If no payment date is mentioned, return exactly: NONE\n"
        "- Do NOT return the reference date unless the client actually promises "
        "to pay on that date.\n"
        "- No prose, no quotes, no explanation."
    )
    today = datetime.utcnow().date()
    user = (
        f"Reference date (today): {today.isoformat()}\n"
        f"Client reply:\n\"\"\"\n{client_message}\n\"\"\"\n\n"
        f"Return only the promised payment date as YYYY-MM-DD, or NONE."
    )

    for attempt in range(2):
        try:
            raw = call_nemotron(system, user, temperature=0.0, max_tokens=64)
            log.warning("extract_promise_date raw (attempt %d): %r", attempt + 1, raw)
            print(f"  [LLM extract] raw response (attempt {attempt + 1}): {raw!r}")
        except Exception as e:
            log.warning("extract_promise_date LLM error (attempt %d): %s", attempt + 1, e)
            print(f"  [LLM extract error (attempt {attempt + 1}): {e}]")
            continue

        iso = _parse_model_output(raw, today)
        if iso:
            print(f"  [LLM extract] parsed date: {iso}")
            return iso

        print(f"  [LLM extract] no date found in response (attempt {attempt + 1})")

    return None