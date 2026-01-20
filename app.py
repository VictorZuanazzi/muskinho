"""
WhatsApp Virtual Friend Bot - Flask Backend (OOP design)
Integrates with Twilio WhatsApp API and OpenAI.
"""

import logging
import os
import random
import re
from dataclasses import dataclass
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable, Optional

from dotenv import load_dotenv
from flask import Flask, Response, request
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse

from openai_client import AIChatClient
from personality import CHAT_PARTNER, get_friend_info, get_system_prompt


def _configure_logging() -> logging.Logger:
    """
    Configure console + rotating file logging.
    Ensures console logs even if other handlers were pre-configured (e.g., Flask).
    """
    base_path = Path(os.getenv("LOG_FILE", "logs/app.log"))
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = base_path.suffix or ".log"
    log_path = base_path.with_name(f"{base_path.stem}-{timestamp}{suffix}")
    if log_path.parent:
        log_path.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s")

    logger = logging.getLogger("muskinho")
    logger.setLevel(logging.INFO)
    logger.propagate = False  # avoid duplicate logs if root handlers exist

    has_rotating = any(
        isinstance(h, RotatingFileHandler) and getattr(h, "baseFilename", None) == str(log_path)
        for h in logger.handlers
    )
    if not has_rotating:
        file_handler = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

    return logger


logger = _configure_logging()


@dataclass(frozen=True)
class BotConfig:
    """Typed configuration container for the bot."""

    account_sid: str
    auth_token: str
    whatsapp_number: str
    openai_api_key: str
    openai_model: str
    openai_base_url: Optional[str]
    max_history: int = 100
    port: int = 5001
    debug: bool = False

    @classmethod
    def from_env(cls) -> "BotConfig":
        load_dotenv()
        return cls(
            account_sid=os.getenv("TWILIO_ACCOUNT_SID", "your_account_sid_here"),
            auth_token=os.getenv("TWILIO_AUTH_TOKEN", "your_auth_token_here"),
            whatsapp_number=os.getenv("TWILIO_WHATSAPP_NUMBER", "whatsapp:+1415523XXXX"),
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            openai_model=os.getenv("OPENAI_MODEL", "llama3"),
            openai_base_url=os.getenv("OPENAI_BASE_URL"),
            max_history=int(os.getenv("MAX_HISTORY", 100)),
            port=int(os.getenv("PORT", 5001)),
            debug=os.getenv("DEBUG", "False").lower() == "true",
        )


class TwilioMessenger:
    """Thin Twilio wrapper that degrades gracefully when credentials are absent."""

    def __init__(self, config: BotConfig, logger: logging.Logger):
        self._logger = logger
        self._from_number = config.whatsapp_number
        try:
            self._client = Client(config.account_sid, config.auth_token)
            self._logger.info("Twilio client initialized.")
        except Exception as exc:
            self._logger.warning(
                "Twilio client initialization failed (messages will only be logged): %s",
                exc,
            )
            self._client = None

    def send_message(self, to: str, body: str) -> None:
        """Send a WhatsApp message or log it when Twilio is not available."""
        if not self._client:
            self._logger.info("Twilio disabled; would send to %s: %s", to, body)
            return

        try:
            self._client.messages.create(from_=self._from_number, body=body, to=to)
            self._logger.info("Message sent to %s", to)
        except Exception as exc:
            self._logger.error("Error sending Twilio message: %s", exc, exc_info=True)


class ChatModelClient:
    """Adapter around AIChatClient with resilient error handling."""

    def __init__(self, client: AIChatClient, model: str, logger: logging.Logger):
        self._client = client
        self._model = model
        self._logger = logger

    def send_messages(self, messages: list[dict[str, str]], temperature: float = 0.7) -> str:
        try:
            return self._client.create_message(messages=messages, model=self._model, temperature=temperature)
        except Exception as exc:
            self._logger.error("Error getting bot response: %s", exc, exc_info=True)
            return "Desculpa, estou com dificuldades agora. Pode tentar de novo em instantes?"


class ResponseShortener:
    """Ensures replies stay within WhatsApp-friendly size limits."""

    def __init__(self, chat_model: ChatModelClient, logger: logging.Logger, max_sentences: int = 2, max_chars: int = 450):
        self._chat_model = chat_model
        self._max_sentences = max_sentences
        self._max_chars = max_chars
        self._logger = logger

    def shorten(self, response: str) -> str:
        text = response.strip()
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]

        if not ((len(sentences) > self._max_sentences) or (len(text) > self._max_chars)):
            return text

        self._logger.info("Shortening response: %s", text)

        try:
            shortened = self._chat_model.send_messages(
                [
                    {
                        "role": "system",
                        "content": (
                            "A resposta está longa para WhatsApp. Reescreva em português, "
                            f"com no máximo {self._max_sentences} frases curtas. "
                            "Caso haja dois topicos na resposta, mantenha apenas o primeiro."
                            "Responda apenas com o texto final, sem citar o original."
                            f"\n\n```{text}```"

                        ),
                    }
                ]
            ).strip()
            return self.shorten(shortened)
        except Exception as exc:
            self._logger.error("Error shortening response: %s", exc, exc_info=True)
            return random.choice(sentences)


class ConversationHistoryManager:
    """Stores and trims per-user conversation history."""

    def __init__(self, system_prompt: str, max_history: int, logger: logging.Logger):
        self._system_prompt = system_prompt
        self._max_history = max_history
        self._logger = logger
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

        try:
            summary = self._summarizer(history)
            self._histories[phone_number] = [
                history[0],  # keep system prompt
                {"role": "assistant", "content": summary},
            ]
            self._logger.info("Conversation history summarized for %s", phone_number)
        except Exception as exc:
            self._logger.error("Failed to summarize history: %s", exc, exc_info=True)
            # If summarization fails, keep last N messages plus system prompt
            self._histories[phone_number] = [history[0]] + history[-self._max_history :]


class WhatsAppBotService:
    """Coordinates OpenAI responses, history, and message shortening."""

    def __init__(
        self,
        history_manager: ConversationHistoryManager,
        chat_model: ChatModelClient,
        shortener: ResponseShortener,
        logger: logging.Logger,
    ):
        self._history_manager = history_manager
        self._chat_model = chat_model
        self._shortener = shortener
        self._logger = logger
        self._history_manager.set_summarizer(self._summarize_history)


    def generate_response(self, phone_number: str, user_message: str) -> str:
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


def create_app(config: Optional[BotConfig] = None) -> Flask:
    """Application factory that wires together dependencies."""
    cfg = config or BotConfig.from_env()

    friend_info = get_friend_info()
    system_prompt = get_system_prompt()

    openai_client = AIChatClient(
        api_key=cfg.openai_api_key,
        base_url=cfg.openai_base_url,
        default_model=cfg.openai_model,
    )
    chat_model = ChatModelClient(openai_client, cfg.openai_model, logger)

    history_manager = ConversationHistoryManager(system_prompt=system_prompt, max_history=cfg.max_history, logger=logger)
    shortener = ResponseShortener(chat_model, logger=logger)
    bot_service = WhatsAppBotService(history_manager, chat_model, shortener, logger=logger)
    messenger = TwilioMessenger(cfg, logger=logger)

    app = Flask(__name__)
    app.config["BOT_SERVICE"] = bot_service
    app.config["MESSENGER"] = messenger
    app.config["FRIEND_INFO"] = friend_info

    @app.route("/webhook", methods=["POST"])
    def webhook():
        """Webhook endpoint for receiving WhatsApp messages from Twilio."""
        try:
            incoming_msg = request.values.get("Body", "").strip()
            sender_number = request.values.get("From", "").strip()

            logger.info("Received message from %s: %s", sender_number, incoming_msg)

            if not incoming_msg:
                logger.warning("Received empty message")
                return Response("OK", status=200)

            bot_response = bot_service.generate_response(sender_number, incoming_msg)
            messenger.send_message(sender_number, bot_response)

            resp = MessagingResponse()
            return Response(str(resp), mimetype="application/xml")
        except Exception as exc:
            logger.error("Error in webhook: %s", exc, exc_info=True)
            resp = MessagingResponse()
            return Response(str(resp), mimetype="application/xml", status=500)

    @app.route("/health", methods=["GET"])
    def health():
        """Health check endpoint."""
        return {
            "status": "healthy",
            "friend": friend_info["name"],
            "message": f"Hi! I'm {friend_info['name']}, your virtual friend!",
        }

    @app.route("/test", methods=["POST"])
    def test():
        """Test endpoint for exercising the bot without Twilio."""
        try:
            data = request.get_json() or {}
            user_message = data.get("message", "").strip()
            phone_number = data.get("phone", "test_user").strip()

            if not user_message:
                return {"error": "No message provided"}, 400

            response = bot_service.generate_response(phone_number, user_message)
            return {
                "user_message": user_message,
                "bot_response": response,
                "friend": friend_info["name"],
                "conversation_length": bot_service.conversation_length(phone_number),
            }
        except Exception as exc:
            logger.error("Error in test endpoint: %s", exc, exc_info=True)
            return {"error": str(exc)}, 500

    @app.route("/reset", methods=["POST"])
    def reset():
        """Reset conversation history for testing."""
        data = request.get_json() or {}
        phone_number = data.get("phone", "test_user").strip()
        bot_service.reset_history(phone_number)
        return {"message": f"Conversation history reset for {phone_number}"}

    @app.route("/friend-info", methods=["GET"])
    def friend_info_route():
        """Get information about the virtual friend."""
        return {
            "name": friend_info["name"],
            "age": friend_info["age"],
            "interests": friend_info["interests"],
            "personality_traits": friend_info["personality_traits"],
        }

    return app


if __name__ == "__main__":
    config = BotConfig.from_env()
    logger.info("Starting %s's WhatsApp bot on port %s", get_friend_info()["name"], config.port)
    logger.info("Virtual friend: %s, %s years old", get_friend_info()["name"], get_friend_info()["age"])

    application = create_app(config)
    application.run(host="0.0.0.0", port=config.port, debug=config.debug)
