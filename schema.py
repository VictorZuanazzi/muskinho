from pydantic import BaseModel, Field
from typing import Optional, Dict, Any


class MessageKey(BaseModel):
    remoteJid: str
    fromMe: bool


class MessageContent(BaseModel):
    conversation: Optional[str] = None


class MessageData(BaseModel):
    key: MessageKey
    pushName: Optional[str] = None
    message: MessageContent


class WebhookPayload(BaseModel):
    data: MessageData
