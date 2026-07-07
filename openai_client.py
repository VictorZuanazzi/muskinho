"""
Unified chat client for OpenAI-compatible providers (OpenAI, Ollama, Grok)
and API-compatible Gemini. Keeps the Flask app agnostic to provider details.
"""

import logging
import os
import random
from time import sleep
from typing import Generator, Optional

import requests
from requests import HTTPError
from dotenv import load_dotenv


class ChatBotBase:
    base_url = ""
    url_chat_suffix = "/chat/completions"
    url_models_suffix = "/models"

    def __init__(self, api_key: str | None = None, allowed_models: Optional[set[str]] = None) -> None:
        self._api_key = api_key
        self._allowed_models = set(
            allowed_models) if allowed_models is not None else None
        self._timeout = 60
        self._model_names: set[str] | None = None
        self._model = None

    @property
    def provider(self) -> str:
        return self.__class__.__name__

    @property
    def model(self) -> str:
        if self._model is None:
            self._model = self.next_model()
        return self._model

    def _get_available_models(self) -> set[str]:
        models_url = self.base_url + self.url_models_suffix
        try:
            resp = requests.get(models_url, headers={
                                "Authorization": f"Bearer {self._api_key}"}, timeout=self._timeout)
            resp.raise_for_status()
        except Exception:
            return set()
        data = resp.json()
        items = data.get("data", [])
        return set([m["id"] for m in items if "id" in m])

    def _call(self, messages: list[dict[str, str]], temperature: float = 0.7, **kwargs) -> str:
        model = self.next_model()
        payload = {"model": model, "messages": messages,
                   "temperature": temperature}
        headers = {"Content-Type": "application/json"}

        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        call_url = self.base_url + self.url_chat_suffix
        response = requests.post(
            call_url, headers=headers, json=payload, timeout=self._timeout)

        response.raise_for_status()
        data = response.json()
        choices = data.get("choices", [])
        for choice in choices:
            if "message" in choice and "content" in choice["message"]:
                return choice["message"]["content"]

        raise ValueError(
            f"Unexpected response from chat API: missing message content. data={data}")

    @property
    def model_names(self) -> set[str]:
        if self._allowed_models is None:
            self._model_names = set()

        if self._model_names is None:
            self._model_names = self._get_available_models()
            if self._allowed_models is not None:
                self._model_names = self._model_names.intersection(
                    self._allowed_models)

        return self._model_names

    def next_model(self) -> str:
        self._model = random.choice(list(self.model_names))
        return self.model  # return the property, not the attribute

    def exclude_model(self, model: str) -> None:
        if model in self.model_names:
            self.model_names.remove(model)

    def __len__(self) -> int:
        return len(self.model_names)


class GrokChatBot(ChatBotBase):
    base_url = "https://api.x.ai/v1"


class OpenAIChatBot(ChatBotBase):
    base_url = "https://api.openai.com/v1"


class OllamaChatBot(ChatBotBase):
    base_url = "http://localhost:11434/v1"


class GeminiChatBot(ChatBotBase):
    base_url = "https://generativelanguage.googleapis.com/v1beta/models"

    def _get_available_models(self) -> set[str]:
        resp = requests.get(self.base_url, params={
                            "key": self._api_key}, timeout=self._timeout)
        resp.raise_for_status()
        data = resp.json()

        model_names: set[str] = set()
        for m in data.get("models", []):
            name = m.get("name")
            methods = m.get("supportedGenerationMethods")
            if (name is None) or (methods is None) or ("generateContent" not in methods):
                continue
            # names come as "models/gemini-1.5-flash-latest"
            model_names.add(name.split("/")[-1])

        return model_names

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
            contents.append(
                {"role": role, "parts": [{"text": msg["content"]}]})
        return contents

    def _call(self, messages: list[dict[str, str]], temperature: float = 0.7) -> str:
        model = self.next_model()
        url = f"{self.base_url}/{model}:generateContent"
        payload = {
            "contents": self._to_gemini_contents(messages),
            "generationConfig": {"temperature": temperature},
        }

        response = requests.post(
            url, params={"key": self._api_key}, json=payload, timeout=self._timeout)
        response.raise_for_status()
        data = response.json()
        candidates = data.get("candidates", [])
        for candidate in candidates:
            parts = candidate.get("content", {}).get("parts", [])
            for part in parts:
                text = part.get("text")
                if text is not None:
                    return text

        raise ValueError(
            f"Unexpected response from Gemini API: missing text. data={data}")


class AIChatClient:
    """Routes chat calls across OpenAI, Ollama, Grok, and Gemini."""

    def __init__(self) -> None:
        self._logger = logging.getLogger("muskinho.ai_client")
        self._max_reply_attempts = 30

        # Ensure environment variables are loaded
        load_dotenv()

        # Keys are resolved from env to avoid exposing provider-specific secrets here.
        self._openai_api_key = os.getenv("OPENAI_API_KEY")
        self._grok_api_key = os.getenv(
            "GROK_API_KEY") or os.getenv("XAI_API_KEY")
        self._gemini_api_key = os.getenv(
            "GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

        self._gemini_chat_bot = GeminiChatBot(
            self._gemini_api_key, allowed_models=self._get_allowed_models("GEMINI_ALLOWED_MODELS"))
        self._grok_chat_bot = GrokChatBot(
            self._grok_api_key, allowed_models=self._get_allowed_models("GROK_ALLOWED_MODELS"))
        self._openai_chat_bot = OpenAIChatBot(
            self._openai_api_key, allowed_models=self._get_allowed_models("OPENAI_ALLOWED_MODELS"))
        self._ollama_chat_bot = OllamaChatBot(
            allowed_models=self._get_allowed_models("OLLAMA_ALLOWED_MODELS"))

        self._chat_bots = [self._gemini_chat_bot, self._grok_chat_bot,
                           self._openai_chat_bot, self._ollama_chat_bot]

    def _get_allowed_models(self, env_var_name: str) -> set[str]:
        raw = os.getenv(env_var_name, None)
        return set(raw.split(",")) if raw is not None else None

    def rotate_chat_bot(self) -> ChatBotBase:
        # Update chatbot list - filter out bots with no available models
        self._chat_bots = [bot for bot in self._chat_bots if len(bot) > 0]
        if not self._chat_bots:
            raise ValueError(
                "No chat bots available - all providers either have no API keys or no available models")
        return random.choice(self._chat_bots)

    def send_messages(self, messages: list[dict[str, str]], temperature: float = 0.7) -> str:
        """Send the conversation to a rotating provider/model set with graceful fallbacks."""

        reply = None
        for attempt in range(self._max_reply_attempts):

            chat_bot = self.rotate_chat_bot()
            try:
                reply = chat_bot._call(messages, temperature)

            except HTTPError as exc:
                self._log_failure_response(exc, exc.response)
                self._logger.warning(
                    "Attempt %s: Failed to call chat bot: %s", attempt + 1, exc)
                if self._is_out_of_credits(exc) or self._is_not_found(exc):
                    chat_bot.exclude_model(chat_bot.model)
                sleep(min(attempt, 3))  # cap sleep at 3s
            except Exception as exc:
                self._logger.warning("Attempt %s: Unexpected error: %s", attempt + 1, exc, exc_info=True)
                sleep(min(attempt, 3))

            if reply is not None:
                self._logger.info("[%s | %s] - Success: %s",
                                chat_bot.provider, chat_bot.model, reply)
                return reply

        self._logger.error("No provider available for chat.")
        return "Desculpa, estou com dificuldades agora. Podemos conversar mais tarde?"

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
