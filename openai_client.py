"""
Unified chat client for OpenAI-compatible providers (OpenAI, Ollama, Grok)
and API-compatible Gemini. Keeps the Flask app agnostic to provider details.
"""

import logging
import os
from typing import Optional

import requests
from requests import HTTPError


class AIChatClient:
    """Routes chat calls across OpenAI, Ollama, Grok, and Gemini."""

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None, default_model: Optional[str] = None):
        self._logger = logging.getLogger("muskinho.ai_client")
        # Keys are resolved from env to avoid exposing provider-specific secrets here.
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.grok_api_key = os.getenv("GROK_API_KEY") or os.getenv("XAI_API_KEY")
        self.gemini_api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

        self.default_model = default_model or os.getenv("OPENAI_MODEL") or "gpt-4o-mini"
        self.base_url = (base_url or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1/chat/completions").rstrip(
            "/"
        )
        self._models_cache: dict[str, list[str]] = {}
        self._over_quota_models: set[str] = set()
        self._invalid_models: set[str] = set()
        self._rotation = self._build_rotation()
        self._rotation_index = 0

    # Public API expected by app.py
    def create_message(self, messages: list[dict[str, str]], model: Optional[str] = None, temperature: float = 0.7) -> str:
        """Send the conversation to a rotating provider/model set with graceful fallbacks."""
        chosen_model = model or self.default_model
        candidate_pairs = []
        if model:
            candidate_pairs.append((self._detect_provider(chosen_model), chosen_model))
        rotation_pairs = self._rotation_plan()
        for pair in rotation_pairs:
            if pair not in candidate_pairs:
                candidate_pairs.append(pair)
        candidate_pairs = [
            (p, m) for (p, m) in candidate_pairs if m not in self._over_quota_models and m not in self._invalid_models
        ]
        candidate_pairs = self._ensure_ollama_last(candidate_pairs)

        last_error: Optional[Exception] = None
        for idx, (provider, pair_model) in enumerate(candidate_pairs):
            if not self._provider_ready(provider):
                last_error = ValueError(f"{provider} credentials missing; skipping.")
                self._logger.warning("Skipping provider=%s (missing credentials)", provider)
                continue

            model_for_provider = self._model_for(provider, pair_model)
            try:
                if provider == "gemini":
                    reply = self._call_gemini(messages, model_for_provider, temperature)
                    self._log_use(provider, model_for_provider)
                    return reply
                if provider == "grok":
                    reply = self._call_openai_like(
                        messages,
                        model_for_provider,
                        temperature,
                        base_url="https://api.x.ai/v1/chat/completions",
                        api_key=self.grok_api_key,
                    )
                    self._log_use(provider, model_for_provider)
                    return reply
                if provider == "ollama":
                    reply = self._call_openai_like(
                        messages,
                        self._strip_provider_prefix(model_for_provider),
                        temperature,
                        base_url=self._ollama_base_url(),
                        api_key=None,  # Ollama typically runs locally without auth
                    )
                    self._log_use(provider, model_for_provider)
                    return reply

                # Default: OpenAI-compatible endpoint (official or any drop-in).
                reply = self._call_openai_like(
                    messages,
                    model_for_provider,
                    temperature,
                    base_url=self.base_url,
                    api_key=self.api_key,
                )
                self._log_use(provider, model_for_provider)
                return reply
            except Exception as exc:  # fallback on failures/out-of-credits
                last_error = exc
                self._logger.warning(
                    "Provider failed, trying next fallback: provider=%s model=%s error=%s",
                    provider,
                    model_for_provider,
                    exc,
                )
                if idx == len(candidate_pairs) - 1:
                    break
                if self._is_out_of_credits(exc):
                    self._mark_over_quota(provider, model_for_provider)
                    continue
                if self._is_not_found(exc):
                    self._mark_invalid(provider, model_for_provider)
                    continue
                # For other errors, still try next provider.
                continue

        if last_error:
            raise last_error
        raise RuntimeError("No provider available for chat completion.")

    # --- Provider helpers -------------------------------------------------
    def _detect_provider(self, model: str) -> str:
        name = model.lower()
        if name.startswith("gemini"):
            return "gemini"
        if name.startswith("grok"):
            return "grok"
        if name.startswith("ollama"):
            return "ollama"
        if "ollama" in self.base_url or "localhost:11434" in self.base_url:
            return "ollama"
        return "openai"

    def _strip_provider_prefix(self, model: str) -> str:
        return model.replace("ollama:", "", 1).replace("ollama/", "", 1)

    def _ollama_base_url(self) -> str:
        return (self.base_url or "http://localhost:11434/v1/chat/completions").rstrip("/")

    def _provider_ready(self, provider: str) -> bool:
        if provider == "openai":
            return bool(self.api_key)
        if provider == "grok":
            return bool(self.grok_api_key)
        if provider == "gemini":
            return bool(self.gemini_api_key)
        return True  # ollama or unknown

    def _model_for(self, provider: str, chosen_model: str) -> str:
        if provider == "gemini":
            return chosen_model if chosen_model.lower().startswith("gemini") else os.getenv("GEMINI_MODEL", "gemini-1.5-flash-latest")
        if provider == "grok":
            return chosen_model if chosen_model.lower().startswith("grok") else os.getenv("GROK_MODEL", "grok-beta")
        if provider == "ollama":
            if chosen_model.lower().startswith("ollama"):
                return chosen_model
            return os.getenv("OLLAMA_MODEL", "llama3")
        # openai or default
        if chosen_model.lower().startswith(("grok", "gemini", "ollama")):
            return self.default_model
        return chosen_model

    def _is_out_of_credits(self, exc: Exception) -> bool:
        if not isinstance(exc, HTTPError):
            return False
        try:
            status = exc.response.status_code
            if status in (402, 429):
                return True
            data = exc.response.json()
            message = str(data)
            return any(token in message.lower() for token in ["insufficient_quota", "insufficient", "quota", "credit", "billing"])
        except Exception:
            return False

    def _is_not_found(self, exc: Exception) -> bool:
        if not isinstance(exc, HTTPError):
            return False
        try:
            return exc.response.status_code == 404
        except Exception:
            return False

    def _log_use(self, provider: str, model: str) -> None:
        self._logger.info("Chat provider used: %s (model=%s)", provider, model)

    def _log_failure_response(self, exc: HTTPError, response: requests.Response) -> None:
        try:
            body = response.json()
        except Exception:
            body = response.text
        self._logger.warning(
            "Provider HTTP error: status=%s url=%s error=%s body=%s",
            response.status_code,
            response.url,
            exc,
            body,
        )

    def _mark_over_quota(self, provider: str, model: str) -> None:
        self._over_quota_models.add(model)
        cached = self._models_cache.get(provider)
        if cached and model in cached:
            self._models_cache[provider] = [m for m in cached if m != model]
        self._logger.warning("Model marked over-quota and removed from rotation: %s (%s)", model, provider)

    def _mark_invalid(self, provider: str, model: str) -> None:
        self._invalid_models.add(model)
        cached = self._models_cache.get(provider)
        if cached and model in cached:
            self._models_cache[provider] = [m for m in cached if m != model]
        self._logger.warning("Model marked invalid (404) and removed from rotation: %s (%s)", model, provider)

    def _allowed_models(self, provider: str) -> list[str]:
        """
        Optional static allowlist of cheapest/free models per provider, via env.
        Env vars: OPENAI_ALLOWED_MODELS, GROK_ALLOWED_MODELS, GEMINI_ALLOWED_MODELS, OLLAMA_ALLOWED_MODELS.
        Comma-separated list; compared case-sensitively to discovered ids.
        """
        var_map = {
            "openai": "OPENAI_ALLOWED_MODELS",
            "grok": "GROK_ALLOWED_MODELS",
            "gemini": "GEMINI_ALLOWED_MODELS",
            "ollama": "OLLAMA_ALLOWED_MODELS",
        }
        key = var_map.get(provider)
        if not key:
            return []
        raw = os.getenv(key)
        if not raw:
            return []
        return [m.strip() for m in raw.split(",") if m.strip()]

    # --- Rotation helpers -------------------------------------------------
    def _build_rotation(self) -> list[tuple[str, str]]:
        """Construct rotation list preferring free models, otherwise cheapest."""
        rotation: list[tuple[str, str]] = []
        provider_order = ["gemini", "openai", "grok", "ollama"]
        for provider in provider_order:
            free_models = self._free_models(provider)
            cheap_model = self._cheap_model(provider)
            models = free_models if free_models else ([cheap_model] if cheap_model else [])
            for m in models:
                rotation.append((provider, m))
        if not rotation:
            rotation = [("ollama", "ollama:llama3")]
        return self._ensure_ollama_last(rotation)

    def _rotation_plan(self) -> list[tuple[str, str]]:
        if not self._rotation:
            self._rotation = [("ollama", "ollama:llama3")]
        idx = self._rotation_index % len(self._rotation)
        ordered = self._rotation[idx:] + self._rotation[:idx]
        self._rotation_index = (self._rotation_index + 1) % len(self._rotation)
        return ordered

    def _ensure_ollama_last(self, pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
        # Deduplicate while keeping order and ensuring ollama at the end.
        seen: set[tuple[str, str]] = set()
        ordered: list[tuple[str, str]] = []
        ollama_pairs: list[tuple[str, str]] = []
        for pair in pairs:
            if pair in seen:
                continue
            seen.add(pair)
            (ollama_pairs if pair[0] == "ollama" else ordered).append(pair)
        return ordered + ollama_pairs

    def _free_models(self, provider: str) -> list[str]:
        if provider == "gemini":
            return self._available_models(provider)
        if provider == "ollama":
            return self._available_models(provider)
        if provider == "openai":
            return self._available_models(provider)
        if provider == "grok":
            return self._available_models(provider)
        return []

    def _cheap_model(self, provider: str) -> Optional[str]:
        if provider == "openai":
            return os.getenv("OPENAI_CHEAP_MODEL", self.default_model)
        if provider == "grok":
            return os.getenv("GROK_CHEAP_MODEL", "grok-beta")
        if provider == "gemini":
            return os.getenv("GEMINI_CHEAP_MODEL", "gemini-1.5-flash")
        if provider == "ollama":
            return os.getenv("OLLAMA_MODEL", "ollama:llama3")
        return None

    # --- Model discovery --------------------------------------------------
    def _available_models(self, provider: str) -> list[str]:
        if provider in self._models_cache:
            return self._models_cache[provider]
        models: list[str] = []
        try:
            if provider == "openai":
                models = self._list_openai_models()
            elif provider == "grok":
                models = self._list_grok_models()
            elif provider == "gemini":
                models = self._list_gemini_models()
            elif provider == "ollama":
                models = self._list_ollama_models()
        except Exception as exc:
            self._logger.warning("Failed to list models for %s: %s", provider, exc)

        # Fallbacks when listing fails or returns empty.
        if not models:
            fallback = self._cheap_model(provider)
            models = [fallback] if fallback else []
            if models:
                self._logger.info("Using fallback model list for %s: %s", provider, models)
        else:
            self._logger.info("Discovered models for %s: %s", provider, models)

        allowed = self._allowed_models(provider)
        if allowed and provider != "ollama":
            models = [m for m in models if m in allowed]
            if not models:
                self._logger.warning("All discovered models for %s filtered by allowed list: %s", provider, allowed)

        models = [m for m in models if m not in self._over_quota_models and m not in self._invalid_models]
        if not models:
            self._logger.warning("All discovered models for %s are filtered (quota/invalid/allowed); keeping empty list", provider)

        self._models_cache[provider] = models
        return models

    def _list_openai_models(self) -> list[str]:
        api_key = self.api_key
        if not api_key:
            return []
        base = self.base_url.rsplit("/chat/completions", 1)[0]
        url = f"{base}/models"
        resp = requests.get(url, headers={"Authorization": f"Bearer {api_key}"}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        items = data.get("data") or []
        return [m["id"] for m in items if "id" in m]

    def _list_grok_models(self) -> list[str]:
        api_key = self.grok_api_key
        if not api_key:
            return []
        url = "https://api.x.ai/v1/models"
        resp = requests.get(url, headers={"Authorization": f"Bearer {api_key}"}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        items = data.get("data") or data.get("models") or []
        ids = []
        for m in items:
            if isinstance(m, dict) and "id" in m:
                ids.append(m["id"])
            elif isinstance(m, str):
                ids.append(m)
        return ids

    def _list_gemini_models(self) -> list[str]:
        key = self.gemini_api_key
        if not key:
            return []
        url = "https://generativelanguage.googleapis.com/v1beta/models"
        resp = requests.get(url, params={"key": key}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        items = data.get("models") or []
        ids = []
        for m in items:
            name = m.get("name")
            if not name:
                continue
            methods = m.get("supportedGenerationMethods") or []
            if "generateContent" not in methods:
                continue
            # names come as "models/gemini-1.5-flash-latest"
            ids.append(name.split("/")[-1])
        return ids

    def _list_ollama_models(self) -> list[str]:
        base = self._ollama_base_url().rsplit("/chat/completions", 1)[0]
        url = f"{base}/models"
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            items = data.get("data") or data.get("models") or []
            ids = []
            for m in items:
                if isinstance(m, dict) and "id" in m:
                    ids.append(f"ollama:{m['id']}")
                elif isinstance(m, dict) and "name" in m:
                    ids.append(f"ollama:{m['name']}")
                elif isinstance(m, str):
                    ids.append(f"ollama:{m}")
            if ids:
                return ids
        except Exception:
            pass
        # Ollama native endpoint (non-OpenAI): /api/tags
        try:
            alt_url = f"{base}/api/tags"
            resp = requests.get(alt_url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            items = data.get("models") or []
            ids = []
            for m in items:
                name = m.get("name")
                if name:
                    ids.append(f"ollama:{name}")
            return ids
        except Exception:
            return []

    @staticmethod
    def _require_key(key: Optional[str], name: str) -> str:
        if not key:
            raise ValueError(f"{name} is required for this provider.")
        return key

    # --- OpenAI-compatible providers (OpenAI, Grok, Ollama) --------------
    def _call_openai_like(
        self, messages: list[dict[str, str]], model: str, temperature: float, base_url: str, api_key: Optional[str]
    ) -> str:
        payload = {"model": model, "messages": messages, "temperature": temperature}
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        response = requests.post(base_url, headers=headers, json=payload, timeout=30)
        try:
            response.raise_for_status()
        except HTTPError as exc:
            self._log_failure_response(exc, response)
            raise

        data = response.json()
        choices = data.get("choices") or []
        if not choices or "message" not in choices[0] or "content" not in choices[0]["message"]:
            raise ValueError("Unexpected response from chat API: missing message content.")
        return choices[0]["message"]["content"]

    # --- Gemini (Google Generative Language) -----------------------------
    def _call_gemini(self, messages: list[dict[str, str]], model: str, temperature: float) -> str:
        key = self._require_key(self.gemini_api_key, "GEMINI_API_KEY/GOOGLE_API_KEY")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        payload = {
            "contents": self._to_gemini_contents(messages),
            "generationConfig": {"temperature": temperature},
        }

        response = requests.post(url, params={"key": key}, json=payload, timeout=30)
        try:
            response.raise_for_status()
        except HTTPError as exc:
            self._log_failure_response(exc, response)
            raise

        data = response.json()
        candidates = data.get("candidates") or []
        parts = candidates[0].get("content", {}).get("parts") if candidates else None
        text = parts[0].get("text") if parts else None
        if not text:
            raise ValueError("Unexpected response from Gemini API: missing text.")
        return text

    @staticmethod
    def _to_gemini_contents(messages: list[dict[str, str]]) -> list[dict[str, object]]:
        """
        Convert OpenAI-style messages into Gemini's `contents` format.
        We collapse messages into a single conversation preserving roles.
        """
        contents: list[dict[str, object]] = []
        for msg in messages:
            role = "user" if msg["role"] == "user" else "model"
            # Gemini supports multiple parts; keep it simple with one text part.
            contents.append({"role": role, "parts": [{"text": msg["content"]}]})
        return contents
