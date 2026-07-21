"""
WhatsApp Virtual Friend Bot - Core Classes
Provides bot configuration, conversation management, and AI chat integration.
"""

import logging
import os
import random
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable, Optional

from dotenv import load_dotenv

from openai_client import AIChatClient
from personality import get_friend_info, get_system_prompt


def _configure_logging() -> logging.Logger:
    """
    Configure console + rotating file logging.
    Ensures console logs even if other handlers were pre-configured.
    """
    base_path = Path(os.getenv("LOG_FILE", "logs/app.log"))
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = base_path.suffix or ".log"
    log_path = base_path.with_name(f"{base_path.stem}-{timestamp}{suffix}")
    log_path.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s")

    logger = logging.getLogger("muskinho")
    logger.setLevel(logging.INFO)
    logger.propagate = False  # avoid duplicate logs if root handlers exist

    file_handler = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    return logger


class ResponseShortener:
    """Ensures replies stay within WhatsApp-friendly size limits."""

    def __init__(self, chat_model: AIChatClient, logger: logging.Logger, max_sentences: int = 3, max_chars: int = 450):
        self._chat_model = chat_model
        self._max_sentences = max_sentences
        self._max_chars = max_chars
        self._logger = logger

    def shorten(self, response: str) -> str:
        text = response.strip()
        questions = [q.strip() for q in re.split(r"\?", text) if q.strip()] if "?" in text else []
        sentences = [s.strip() for s in re.split(r"(?<=[.!])\s+", text) if s.strip()]
        n_sentences = len(sentences) + len(questions)
        print(sentences, questions)

        if (n_sentences <= self._max_sentences) and (len(text) <= self._max_chars):
            return text

        self._logger.info("Shortening response (chars: %s, sentences: %s): %s", len(text), n_sentences, text)
        
        emojis = [
                    "😘", "🌹", "🌹🌹", "😊", "🙂", "😌", "🌸💐", "🌷🌺", "❤️", 
                    "💕", "💗", "✨✨✨", "🦋🌈", "💐", "🌸", "🌷", "🌺", "🌳",
                ] + ([""] * 30)

        if len(questions) > 0:
            return f"{questions[0]}? {random.choice(emojis)}"

        return "! ".join(sentences[:self._max_sentences]) + f" {random.choice(emojis)}{random.choice(emojis)}"


class ConversationHistoryManager:
    """Stores and trims per-user conversation history."""

    def __init__(self, system_prompt: str, logger: logging.Logger, max_history: int = 100):
        self._system_prompt = system_prompt
        self._logger = logger
        self._max_history = max_history
        self._histories: dict[str, list[dict[str, str]]] = {}
        self._summarizer: Optional[Callable[[list[dict[str, str]]], str]] = None

    def set_summarizer(self, summarizer: Callable[[list[dict[str, str]]], str]) -> None:
        self._summarizer = summarizer

    def get_history(self, phone_number: str) -> list[dict[str, str]]:
        if phone_number not in self._histories:
            self._histories[phone_number] = [
                {"role": "system", "content": self._system_prompt}
            ]
        return self._histories[phone_number]

    def add_message(self, phone_number: str, role: str, content: str) -> None:
        history = self.get_history(phone_number)
        history.append({"role": role, "content": content})
        self._trim_history(phone_number)

    def reset(self, phone_number: str) -> None:
        if phone_number in self._histories:
            del self._histories[phone_number]

    def conversation_length(self, phone_number: str) -> int:
        return len(self.get_history(phone_number))

    def _trim_history(self, phone_number: str) -> None:
        history = self._histories[phone_number]
        if len(history) <= self._max_history + 1 or not self._summarizer:
            return

        half_history = self._max_history // 4
        self._histories[phone_number] = history[: half_history] + history[-half_history :]

        # try:
        #     summary = self._summarizer(history)
        #     self._histories[phone_number] = [
        #         history[0],  # keep system prompt
        #         {"role": "assistant", "content": summary},
        #     ]
        #     self._logger.info("Conversation history summarized for %s", phone_number)
        # except Exception as exc:
        #     self._logger.error("Failed to summarize history: %s", exc, exc_info=True)
        #     # If summarization fails, keep last N messages plus system prompt
        #     self._histories[phone_number] = [history[0]] + history[-self._max_history :]


class WhatsAppBotService:
    """Coordinates OpenAI responses, history, and message shortening."""

    def __init__(
        self,
        history_manager: ConversationHistoryManager,
        chat_model: AIChatClient,
        shortener: ResponseShortener,
        logger: logging.Logger,
    ):
        self._history_manager = history_manager
        self._chat_model = chat_model
        self._shortener = shortener
        self._logger = logger
        self._history_manager.set_summarizer(self._summarize_history)


    def generate_response(self, phone_number: str, user_message: str) -> str:
        self._logger.info("Processing message for %s: %.80s", phone_number, user_message)
        history = self._history_manager.get_history(phone_number)
        self._history_manager.add_message(phone_number, "user", user_message)

        response = self._chat_model.send_messages(history)
        response = self._shortener.shorten(response)

        self._history_manager.add_message(phone_number, "assistant", response)
        self._logger.info("Generated response for %s: %s", phone_number, response)
        return response

    def reset_history(self, phone_number: str) -> None:
        self._history_manager.reset(phone_number)

    def conversation_length(self, phone_number: str) -> int:
        return self._history_manager.conversation_length(phone_number)

    def _summarize_history(self, history: list[dict[str, str]]) -> str:
        summarization_prompt = [{"role": "system", "content": "Resuma a conversa em 1 parágrafo."}] + history
        return self._chat_model.send_messages(summarization_prompt, temperature=0.3)


