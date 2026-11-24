"""Runtime configuration and deterministic scoring constants."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")
CACHE_DIR = PROJECT_ROOT / ".cache"

DEFAULT_MODEL = "gemini-3.5-flash-lite"
GEMINI_MODEL = os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
MAX_PAGES = int(os.getenv("MAX_PAGES", "150"))
MIN_AVERAGE_CHARS_PER_PAGE = int(os.getenv("MIN_AVERAGE_CHARS_PER_PAGE", "200"))
MAX_EMPTY_PAGE_RATIO = float(os.getenv("MAX_EMPTY_PAGE_RATIO", "0.50"))
MAX_REPAIR_ATTEMPTS = 2
LLM_TIMEOUT_SECONDS = int(os.getenv("LLM_TIMEOUT_SECONDS", "120"))
LLM_MAX_RETRIES = 3
LLM_MAX_OUTPUT_TOKENS = 65_536
FUZZY_MATCH_THRESHOLD = 92

FIT_WEIGHTS = {
    "scope_fit": 0.35,
    "eligibility": 0.25,
    "delivery_feasibility": 0.20,
    "commercial_risk": 0.20,
}
SCOPE_NO_BID_THRESHOLD = 2
LOW_BID_SCORE_WARNING = 4
HIGH_NO_BID_SCORE_WARNING = 8
