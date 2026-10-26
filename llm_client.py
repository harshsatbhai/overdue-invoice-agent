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
# Flexible date parsing
# ------------------------------------------------------------------
_DATE_FORMATS = [
    "%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y",
    "%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y",
    "%B %d %Y", "%b %d %Y", "%d-%B-%Y", "%d-%b-%Y",
]


def _normalize_date_string(s: str) -> str | None:
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
    """Given a string, return ISO date or None. Handles:
      - Explicit NONE
      - Strict fullmatch
      - ISO dates anywhere (prefer last)
      - dd-mm-yyyy / dd/mm/yyyy (prefer last)
      - Natural language month/day
    """
    text = text.strip()
    text = re.sub(r'^```[a-zA-Z]*\s*|\s*```$', '', text).strip()

    if re.fullmatch(r'NONE\.?', text, flags=re.IGNORECASE):
        return None

    strict = _normalize_date_string(text)
    if strict:
        return strict

    # ISO anywhere — prefer last
    iso_matches = re.findall(r'\b(\d{4})-(\d{2})-(\d{2})\b', text)
    for y, m, d in reversed(iso_matches):
        try:
            return datetime(int(y), int(m), int(d)).strftime("%Y-%m-%d")
        except ValueError:
            continue

    # dd-mm-yyyy anywhere — prefer last
    dmy_matches = re.findall(r'\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b', text)
    for d, m, y in reversed(dmy_matches):
        try:
            return datetime(int(y), int(m), int(d)).strftime("%Y-%m-%d")
        except ValueError:
            continue

    # Natural language: "December 24th", "24 December", "Dec 24 [2026]"
    month_names = r'(?:january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)'

    # "December 24th [2026]" — prefer last occurrence
    md_matches = list(re.finditer(
        rf'\b({month_names})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s*(\d{{4}}))?\b',
        text, flags=re.IGNORECASE,
    ))
    for m in reversed(md_matches):
        iso = _build_date(m.group(1), int(m.group(2)), m.group(3), today)
        if iso:
            return iso

    # "24th [of] December [2026]" — prefer last occurrence
    dm_matches = list(re.finditer(
        rf'\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({month_names})\.?(?:,?\s*(\d{{4}}))?\b',
        text, flags=re.IGNORECASE,
    ))
    for m in reversed(dm_matches):
        iso = _build_date(m.group(2), int(m.group(1)), m.group(3), today)
        if iso:
            return iso

    return None


def _build_date(month_name: str, day: int, year_str: str | None, today: date) -> str | None:
    month_num = _month_to_num(month_name)
    if not month_num:
        return None
    try:
        if year_str:
            return datetime(int(year_str), month_num, day).strftime("%Y-%m-%d")
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
    """Extract a promised payment date from a client reply.
    Returns ISO (YYYY-MM-DD) or None.

    Strategy:
      1. Fast path: if the message itself contains a parseable date, return it
         without calling the LLM (avoids reasoning-model quirks entirely).
      2. Otherwise, call the LLM with a strict prompt and large token budget,
         then parse the raw output (preferring the last date found, since
         reasoning models mention the reference date first).
    """
    today = datetime.utcnow().date()

    # ── Fast path: parse the client's text directly ──
    fast = _parse_model_output(client_message, today)
    if fast:
        print(f"  [LLM extract] fast-path parsed from client message: {fast}")
        return fast

    # ── LLM path: only needed for relative dates ("next Friday", "in two weeks") ──
    system = (
        "You are a strict data-extraction bot. Extract the payment date the client "
        "promises in the reply.\n\n"
        "OUTPUT RULES — follow exactly:\n"
        "- Do NOT explain, reason, restate the message, or add commentary.\n"
        "- Your ENTIRE response must be ONE of:\n"
        "    (a) a single ISO date in YYYY-MM-DD format, OR\n"
        "    (b) the single word NONE.\n"
        "- No quotes, no code fences, no punctuation around the date.\n\n"
        "DATE RULES:\n"
        "- Resolve relative dates against the reference date: 'next Friday', "
        "'in two weeks', 'end of the month', 'tomorrow', 'the 15th'.\n"
        "- If a month/day is given without a year, use the NEXT occurrence on or "
        "after the reference date.\n"
        "- Do NOT return the reference date unless the client actually promises "
        "to pay on that date.\n"
        "- If no payment date is mentioned, return NONE."
    )
    user = (
        f"Reference date: {today.isoformat()}\n"
        f"Client reply:\n\"\"\"\n{client_message}\n\"\"\"\n\n"
        f"Answer (single YYYY-MM-DD or NONE):"
    )

    for attempt in range(2):
        try:
            # 512 tokens: reasoning models can finish thinking and still emit
            # the final answer on the last line. The parser prefers the last
            # ISO date, so trailing reasoning does not cause the wrong answer.
            raw = call_nemotron(system, user, temperature=0.0, max_tokens=512)
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