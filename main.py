import base64
import json
import os
from fastapi import FastAPI, Request, Response
import requests

from app import BotConfig, ChatModelClient, ConversationHistoryManager, ResponseShortener, WhatsAppBotService, logger
from openai_client import AIChatClient
from personality import get_friend_info, get_system_prompt

app = FastAPI()

revolution_url = os.getenv("REVOLUTION_API_URL","https://evolution-api-v1-8-7-ooq4.onrender.com")
api_key = os.getenv("REVOLUTION_API_KEY","teste")
origin_number = os.getenv("ORIGIN_NUMBER","")
destination_number = os.getenv("DESTINATION_NUMBER","XXX")
origin_number = os.getenv("ORIGIN_NUMBER", "XXX")

instance_name = "evo_imorales"
instance_token = os.getenv("instance_token", "teste123-token")
webhook_url="https://untestamentary-nonmythologically-lucile.ngrok-free.dev/webhook"

headers= {"apiKey": f"{api_key}"}

cfg = BotConfig.from_env()

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


@app.get("/qrcode")
def qrcode():
    def create_session_return_qrcode():
        r = requests.post(
            f"{revolution_url}/instance/create",
            json={
                "instanceName": instance_name,
                "token": instance_token,
                "qrcode": True,
                "number": origin_number,
                "webhook": webhook_url,
                "webhook_by_events": True,
                "events": [
                    "SEND_MESSAGE",
                    "MESSAGES_UPSERT",
                ]    
            },
            headers=headers,
            timeout=30
        )
        print(r.json())
        qrcode_response = r.json().get("qrcode", None)
        if qrcode_response is None:
            return f"Erro ao gerar QRCode: {r.json()}"

        # Remove data URL prefix and fix missing padding before decoding
        base64_payload = qrcode_response.get("base64", "")
        if base64_payload.startswith("data:"):
            _, _, base64_payload = base64_payload.partition(",")
        missing_padding = (-len(base64_payload)) % 4
        if missing_padding:
            base64_payload += "=" * missing_padding

        image_bytes = base64.b64decode(base64_payload)
        return image_bytes
    r = requests.get(f"{revolution_url}/instance/fetchInstances",headers=headers,timeout=30)
    response = r.json()
    print(response)
    if len(response) >= 1:
        if response[0]["instance"]["status"]!="open":

            r = requests.delete(f"{revolution_url}/instance/delete/{instance_name}",headers=headers,timeout=30)
            print(r.json())
            image_bytes = create_session_return_qrcode()
            return Response(content=image_bytes, 
            media_type="image/png"
            )
        else:
            return "Já existe sessão ativa"
    else:
        image_bytes = create_session_return_qrcode()
        return Response(content=image_bytes, media_type="image/png")


@app.post("/webhook/messages-upsert")
async def webhook(request: Request):
    json_data = await request.json()
    print(json.dumps(json_data, indent=4))

    from_me = json_data["data"]["key"]["fromMe"]
    if not from_me:
        bot_response = bot_service.generate_response(destination_number, json_data["data"]["message"]["conversation"])
        print(bot_response)
        r = requests.post(f"{revolution_url}/message/sendText/{instance_name}",
            json = {
                "number": destination_number,
                "options": {
                    "delay": 1000,
                    "presence": "composing",
                    "linkPreview": False,
                },
                "textMessage": {"text": bot_response}, 
            },
            headers=headers,
            timeout=30
        )
        print(r.json())