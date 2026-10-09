import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

RODIUMAI_URL = "https://api.rodiumai.io/v1/chat/completions"


def get_rodiumai_api_key() -> str:
    key = os.getenv("RODIUMAI_API_KEY")
    if not key:
        raise RuntimeError("RODIUMAI_API_KEY est manquante dans l'environnement.")
    return key

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

# Modèles légers (faible coût / consommation de tokens) adaptés au tutorat.
DEFAULT_MODEL = os.getenv("RODIUMAI_MODEL", "openai/gpt-4o-mini")
LOW_COST_MODELS = (
    "openai/gpt-4o-mini",
    "google/gemini-2.0-flash-001",
)

PREVIEW_LENGTH = 60
NOTIFICATION_EVERY = 10
NOTIFICATION_TEXT = "Notification système : une dizaine de messages échangés dans ce fil."

NOTIFICATION_ROLE = "system-notification"
NOTE_ROLE = "note"

# Roles persisted in the DB but never sent to the LLM as-is.
NON_LLM_ROLES = {NOTIFICATION_ROLE, NOTE_ROLE}
LLM_ROLES = {"user", "assistant"}


def get_allowed_models() -> list[str]:
    raw = os.getenv("RODIUMAI_ALLOWED_MODELS", "").strip()
    if raw:
        models = [m.strip() for m in raw.split(",") if m.strip()]
    else:
        models = list(LOW_COST_MODELS)
        if DEFAULT_MODEL not in models:
            models.insert(0, DEFAULT_MODEL)
    # Preserve order while deduplicating.
    seen: set[str] = set()
    unique: list[str] = []
    for model in models:
        if model not in seen:
            seen.add(model)
            unique.append(model)
    return unique


def get_default_model() -> str:
    allowed = get_allowed_models()
    configured = os.getenv("RODIUMAI_MODEL", "").strip()
    if configured and configured in allowed:
        return configured
    if DEFAULT_MODEL in allowed:
        return DEFAULT_MODEL
    return allowed[0]


def validate_model(model: str) -> None:
    if model not in get_allowed_models():
        allowed = ", ".join(get_allowed_models())
        raise ValueError(f"Modèle non autorisé. Choisissez parmi : {allowed}")


@lru_cache
def load_system_prompt() -> str:
    path = PROMPTS_DIR / "system.md"
    return path.read_text(encoding="utf-8")
