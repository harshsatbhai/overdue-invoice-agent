import requests
from config import Config
from database import get_latest_sent_reminder_id, update_promise
from llm_client import extract_promise_date

def sync_promises():
    """Agent automatically polls the portal for client replies, extracts dates via LLM, and logs them."""
    try:
        resp = requests.get(f"{Config.PORTAL_BASE_URL}/client-replies", timeout=5)
        if resp.status_code != 200:
            return
        replies = resp.json()
    except Exception:
        return  # Portal not reachable

    for inv_id, message in replies.items():
        reminder_id = get_latest_sent_reminder_id(inv_id)
        if reminder_id:
            print(f"  [Agent] Extracting promise from reply for {inv_id}...")
            date_str = extract_promise_date(message)
            if date_str:
                update_promise(reminder_id, date_str, note="Auto-extracted from client reply")
                print(f"  [Agent] Logged promise for {inv_id}: {date_str}")