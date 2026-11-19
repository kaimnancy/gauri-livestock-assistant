"""Central model factory for all Gauri agents."""

from __future__ import annotations

import logging
import os
from typing import Union

from dotenv import load_dotenv
from google.adk.models.lite_llm import LiteLlm

load_dotenv()

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "ollama_chat/qwen2.5:7b"
DEFAULT_OLLAMA_BASE = "http://localhost:11434"


def get_model(role: str = "default") -> Union[LiteLlm, str]:
    """Return the configured model for a given agent role.

    Resolution order:
        1. Role-specific env var: GAURI_MODEL_<ROLE> (e.g., GAURI_MODEL_ORCHESTRATOR)
        2. Global env var: GAURI_MODEL
        3. Fallback default: ollama_chat/qwen2.5:7b

    Native Gemini model names are returned as strings (ADK native support).
    All other providers (Ollama, Groq, etc.) are wrapped in LiteLlm.
    """
    role_env_key = f"GAURI_MODEL_{role.upper()}"
    model_name = os.getenv(role_env_key) or os.getenv("GAURI_MODEL") or DEFAULT_MODEL

    if model_name.startswith("gemini"):
        logger.info("Model for role '%s': %s (native ADK)", role, model_name)
        return model_name

    # Ensure Ollama base URL is set when using local Ollama models
    if model_name.startswith("ollama") and not os.getenv("OLLAMA_API_BASE"):
        os.environ["OLLAMA_API_BASE"] = DEFAULT_OLLAMA_BASE

    logger.info("Model for role '%s': %s (via LiteLlm)", role, model_name)
    return LiteLlm(model=model_name)
