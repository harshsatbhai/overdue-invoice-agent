import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    LLM_API_KEY = os.getenv("OPENROUTER_API_KEY") or os.getenv("NVIDIA_API_KEY")
    LLM_MODEL = os.getenv("LLM_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")
    LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1")
    PORTAL_BASE_URL = os.getenv("PORTAL_BASE_URL", "http://127.0.0.1:8000")
    REQUIRE_HUMAN_APPROVAL = os.getenv("REQUIRE_HUMAN_APPROVAL", "true").lower() == "true"
    DB_PATH = "data/agent.db"

    # Tone escalation thresholds (days overdue)
    TONE_FRIENDLY_DAYS = 7      # 1-7 days: friendly reminder
    TONE_FIRM_DAYS = 14         # 8-14 days: firm reminder
    TONE_FINAL_DAYS = 30        # 15+: final notice (still polite, but escalated)

    # Approved tone templates
    APPROVED_TONES = ["friendly", "firm", "final_notice"]