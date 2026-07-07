import argparse
import base64
import json
import os
from typing import Any, Dict
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
import requests

from schema import WebhookPayload
from utils import ConversationHistoryManager, ResponseShortener, WhatsAppBotService, _configure_logging
from openai_client import AIChatClient
from personality import get_system_prompt
from registry import PhoneNumberRegistry

logger = _configure_logging()


class WhatsAppChatClient:
    default_webhook_url = "https://untestamentary-nonmythologically-lucile.ngrok-free.dev/webhook"

    def __init__(self,
                 revolution_api_url: str = None,
                 revolution_api_key: str = None,
                 origin_number: str = None,
                 destination_number: str = None,
                 instance_name: str = None,
                 instance_token: str = None,
                 webhook_url: str = None):

        load_dotenv()
        self._app = FastAPI()
        # Use CLI arguments if provided, otherwise fall back to environment variables
        self._revolution_url = revolution_api_url or os.getenv(
            "REVOLUTION_API_URL", "")
        self.revolution_api_key = revolution_api_key or os.getenv(
            "REVOLUTION_API_KEY", "")
        self._origin_number = origin_number or os.getenv("ORIGIN_NUMBER", "")
        self._destination_number = destination_number or os.getenv(
            "DESTINATION_NUMBER", "")
        self._instance_name = instance_name or os.getenv("INSTANCE_NAME", "")
        self._instance_token = instance_token or os.getenv(
            "instance_token", "")

        self._webhook_url = webhook_url or self.default_webhook_url
        self._headers = {"apiKey": f"{self.revolution_api_key}"}

        self._system_prompt = get_system_prompt()

        self._chat_model = AIChatClient()
        self._history_manager = ConversationHistoryManager(
            system_prompt=self._system_prompt, logger=logger)
        self._shortener = ResponseShortener(self._chat_model, logger=logger)
        self._bot_service = WhatsAppBotService(
            self._history_manager, self._chat_model, self._shortener, logger=logger)

        self._registry = PhoneNumberRegistry.from_env()
        if not os.getenv("REGISTRY_SECRET_KEY"):
            logger.warning(
                "REGISTRY_SECRET_KEY not set; registry will not persist across restarts")

        # Register routes
        self._register_routes()

    def _register_routes(self):
        """Register FastAPI routes."""
        # self._app.get("/qrcode")(self.qrcode)
        self._app.post("/webhook/messages-upsert")(self.messages_upsert)

    @property
    def app(self) -> FastAPI:
        return self._app

    def _send_text(self, number: str, text: str) -> None:
        requests.post(
            f"{self._revolution_url}/message/sendText/{self._instance_name}",
            json={
                "number": number,
                "text": text,
                "options": {"delay": 1000, "presence": "composing", "linkPreview": False},
            },
            headers=self._headers,
            timeout=30,
        )

    async def messages_upsert(self, request: Dict[Any, Any]) -> None:
        json_data = request
        print(json.dumps(json_data))
        logger.debug("Received webhook payload: %s",
                     json.dumps(json_data, indent=4))

        from_me = request["data"]["key"]["fromMe"]
        user_message = request['data']['message']['conversation']
        if request['data']["status"] == "ERROR":
            logger.info(
                "Received message from_me=%s: %s with error, ignoring", from_me, user_message)
            return
        logger.info("Received message from_me=%s: %s", from_me, user_message)

        if from_me:
            return

        remoteJid = request['data']['key']['remoteJid']

        destination_number = self._registry.get_number(remoteJid)
        if destination_number is None:
            destination_number, is_new = self._registry.try_register(
                remoteJid, user_message)
            if is_new:
                self._send_text(
                    destination_number, f"{destination_number} added. You can now chat with Elon Muskinho.")
                user_message = "Ola, como voce se chama?"
            else:
                logger.info(
                    "Message from remoteJid %s, user %s, not in contacts. Ignoring",
                    remoteJid, request['data']['pushName'])
                return

        bot_response = self._bot_service.generate_response(
            destination_number, user_message)
        logger.info("Sending bot response to %s: %s",
                    destination_number, bot_response)
        self._send_text(destination_number, bot_response)

    def terminal_chat(self):
        """Interactive terminal chat using the same bot logic as messages_upsert."""
        print("=" * 60)
        print("Terminal Chat Mode - Type 'exit' or 'quit' to end")
        print("=" * 60)
        print()

        # Use a consistent identifier for terminal chat conversations
        terminal_user_id = "terminal"

        while True:
            try:
                # Get user input
                user_message = input("You: ").strip()

                # Skip empty messages
                if not user_message:
                    continue

                # Check for exit commands
                if user_message.lower() in ['exit', 'quit', 'q']:
                    print("\nGoodbye!")
                    break

                # Generate bot response using the same logic as messages_upsert
                bot_response = self._bot_service.generate_response(
                    terminal_user_id, user_message)
                print(f"Bot: {bot_response}\n")

            except (KeyboardInterrupt, EOFError):
                print("\n\nGoodbye!")
                break
            except Exception as e:
                logger.error("Error in terminal chat: %s", e, exc_info=True)
                print(f"Error: {e}\n")


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="WhatsApp Chat Client with Evolution API integration"
    )
    parser.add_argument(
        "--revolution-api-url",
        type=str,
        default=None,
        help="Revolution API URL (overrides REVOLUTION_API_URL env var)"
    )
    parser.add_argument(
        "--revolution-api-key",
        type=str,
        default=None,
        help="API key for Revolution API (overrides REVOLUTION_API_KEY env var)"
    )
    parser.add_argument(
        "--origin-number",
        type=str,
        default=None,
        help="Origin phone number (overrides ORIGIN_NUMBER env var)"
    )
    parser.add_argument(
        "--destination-number",
        type=str,
        default=None,
        help="Destination phone number (overrides DESTINATION_NUMBER env var)"
    )
    parser.add_argument(
        "--instance-name",
        type=str,
        default=None,
        help="Instance name (overrides INSTANCE_NAME env var)"
    )
    parser.add_argument(
        "--instance-token",
        type=str,
        default=None,
        help="Instance token (overrides instance_token env var)"
    )
    parser.add_argument(
        "--webhook-url",
        type=str,
        default=None,
        help="Webhook URL (overrides default webhook URL)"
    )
    parser.add_argument(
        "-c",
        "--chat",
        action="store_true",
        help="Start terminal chat mode instead of web server"
    )
    # Use parse_known_args to ignore unknown arguments (like uvicorn's --reload)
    args, _ = parser.parse_known_args()
    return args


# Create instance - routes are automatically registered in __init__
# parse_known_args() ignores unknown arguments (like uvicorn's --reload, main:app, etc.)
args = parse_args()
whatsapp_client = WhatsAppChatClient(
    revolution_api_url=args.revolution_api_url,
    revolution_api_key=args.revolution_api_key,
    origin_number=args.origin_number,
    destination_number=args.destination_number,
    instance_name=args.instance_name,
    instance_token=args.instance_token,
    webhook_url=args.webhook_url
)

# Always create app for uvicorn imports
app = whatsapp_client.app

# If --chat flag is set and running directly, run terminal chat instead
if args.chat and __name__ == "__main__":
    whatsapp_client.terminal_chat()
