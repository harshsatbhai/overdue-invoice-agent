import requests
from config import Config
from database import get_latest_sent_reminder_id, update_promise
from llm_client import extract_promise_date


def sync_promises():
    """Agent automatically polls the portal for client replies, extracts dates via LLM, and logs them."""
    try:
        resp = requests.get(f"{Config.PORTAL_BASE_URL}/client-replies", timeout=5)
        if resp.status_code != 200:
            print(f"  [Agent] sync_promises: portal returned {resp.status_code}")
            return
        replies = resp.json()
    except Exception as e:
        print(f"  [Agent] sync_promises: portal unreachable: {e}")
        return

    if not replies:
        print("  [Agent] sync_promises: no client replies to process")
        return

    for inv_id, message in replies.items():
        reminder_id = get_latest_sent_reminder_id(inv_id)
        if not reminder_id:
            print(
                f"  [Agent] sync_promises: no sent reminder without a promise "
                f"for {inv_id}; skipping (already recorded or never sent)"
            )
            continue

        print(f"  [Agent] Extracting promise from reply for {inv_id}: {message!r}")
        date_str = extract_promise_date(message)
        if date_str:
            try:
                update_promise(reminder_id, date_str, note="Auto-extracted from client reply")
                print(f"  [Agent] Logged promise for {inv_id}: {date_str}")
            except Exception as e:
                print(f"  [Agent] update_promise failed for {inv_id}: {e}")
        else:
            print(f"  [Agent] No promise date extracted for {inv_id}")