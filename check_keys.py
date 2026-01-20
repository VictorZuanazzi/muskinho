"""
Lightweight connectivity/credits check for all configured chat providers.
Uses a tiny chat completion per provider to validate keys and quota.
"""

import os
from typing import Optional, Tuple, List

import requests
from dotenv import load_dotenv
from requests import HTTPError

load_dotenv()


def _print_status(ok: bool, provider: str, model: str, detail: str) -> None:
    icon = "✓" if ok else "❌"
    print(f"{icon} {provider:<8} model={model:<24} {detail}")


def _status_from_http_error(exc: HTTPError) -> str:
    status = exc.response.status_code if exc.response else "?"
    try:
        body = exc.response.json()
    except Exception:
        body = exc.response.text if exc.response else ""
    prefix = f"HTTP {status}"
    if status in (401, 403):
        return f"{prefix} - invalid/unauthorized key ({body})"
    if status in (402, 429):
        return f"{prefix} - likely out of credits ({body})"
    return f"{prefix} - {body}"


def check_openai_like(name: str, url: str, key: Optional[str], model: str) -> None:
    if not url:
        _print_status(False, name, model, "missing base URL")
        return
    if key is None and "ollama" not in url:
        _print_status(False, name, model, "missing API key")
        return

    payload = {"model": model, "messages": [{"role": "user", "content": "ping"}], "temperature": 0}
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        resp.raise_for_status()
        _print_status(True, name, model, "OK")
    except HTTPError as exc:
        _print_status(False, name, model, _status_from_http_error(exc))
    except Exception as exc:
        _print_status(False, name, model, f"{type(exc).__name__}: {exc}")


def _pick_gemini_chat_model() -> Tuple[Optional[str], Optional[str]]:
    """
    Returns (model_id, detail) choosing the first model that supports generateContent.
    """
    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key:
        return None, "missing GEMINI_API_KEY/GOOGLE_API_KEY"
    url = "https://generativelanguage.googleapis.com/v1beta/models"
    try:
        resp = requests.get(url, params={"key": key}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        models: List[dict] = data.get("models") or []
        chat_models = [
            m.get("name").split("/")[-1]
            for m in models
            if "generateContent" in (m.get("supportedGenerationMethods") or [])
        ]
        if chat_models:
            return chat_models[0], f"picked from ListModels ({len(chat_models)} available)"
        return None, "no generateContent models returned by ListModels"
    except HTTPError as exc:
        return None, _status_from_http_error(exc)
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def check_gemini(model: Optional[str] = None) -> None:
    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key:
        _print_status(False, "gemini", model, "missing GEMINI_API_KEY/GOOGLE_API_KEY")
        return
    chosen_model = model
    detail = "env default"
    if not chosen_model:
        chosen_model, detail = _pick_gemini_chat_model()
    if not chosen_model:
        _print_status(False, "gemini", "(none)", detail or "no model available")
        return

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{chosen_model}:generateContent"
    payload = {"contents": [{"role": "user", "parts": [{"text": "ping"}]}], "generationConfig": {"temperature": 0}}
    try:
        resp = requests.post(url, params={"key": key}, json=payload, timeout=10)
        resp.raise_for_status()
        _print_status(True, "gemini", chosen_model, f"OK ({detail})")
    except HTTPError as exc:
        _print_status(False, "gemini", chosen_model, _status_from_http_error(exc))
    except Exception as exc:
        _print_status(False, "gemini", chosen_model, f"{type(exc).__name__}: {exc}")


def main():
    openai_key = os.getenv("OPENAI_API_KEY")
    openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    openai_base = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1/chat/completions")

    grok_key = os.getenv("GROK_API_KEY") or os.getenv("XAI_API_KEY")
    grok_model = os.getenv("GROK_MODEL", "grok-beta")
    grok_base = "https://api.x.ai/v1/chat/completions"

    gemini_model = os.getenv("GEMINI_MODEL")  # optional; if unset we auto-pick

    ollama_model = os.getenv("OLLAMA_MODEL", "llama3")
    ollama_base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1/chat/completions")

    print("\n🔍 Chat provider key/quota check\n")
    check_openai_like("openai", openai_base, openai_key, openai_model)
    check_openai_like("grok", grok_base, grok_key, grok_model)
    check_gemini(gemini_model)
    check_openai_like("ollama", ollama_base, None, ollama_model)
    print("\nDone.\n")


if __name__ == "__main__":
    main()
