# Muskinho WhatsApp Bot
 
FastAPI backend that connects **Evolution API** (WhatsApp) to an AI chat persona. Evolution API posts inbound messages to `/webhook/messages-upsert`; the app replies via Evolution API and can run a terminal chat mode for local testing.

## Features

- **Evolution API** integration for WhatsApp (no Twilio)
- **Multi-provider AI**: OpenAI, Grok, Gemini, or Ollama via a unified chat client
- Configurable personality via `personality.py`
- Conversation history and response shortening
- Optional `--chat` flag for terminal chat without WhatsApp

## Configuration

Copy `env.example` to `.env` and set:

| Variable | Description |
|----------|-------------|
| `REVOLUTION_API_URL` | Evolution API base URL |
| `REVOLUTION_API_KEY` | Evolution API key |
| `ORIGIN_NUMBER` | Your WhatsApp number (origin) |
| `DESTINATION_NUMBER` | Default destination number |
| `INSTANCE_NAME` | Evolution API instance name |
| `PORT` | Server port (default `5001`) |
| `OPENAI_API_KEY`, `OPENAI_BASE_URL` | OpenAI (or compatible) API |
| `OPENAI_ALLOWED_MODELS` | Comma-separated allowed models (e.g. `gpt-4o-mini`) |
| `GEMINI_API_KEY`, `GEMINI_ALLOWED_MODELS` | Optional Gemini |
| `GROK_API_KEY`, `GROK_ALLOWED_MODELS` | Optional Grok |
| `OLLAMA_BASE_URL`, `OLLAMA_ALLOWED_MODELS` | Optional Ollama |

Optional: `LOG_FILE` to override rotating log path (defaults under `logs/`).

## Run locally

```bash
pip install -r requirements.txt
uvicorn main:app --reload --port 5001
```

Terminal chat (no webhook):

```bash
python main.py --chat
```

## Run with Docker

```bash
docker build -t muskinho .
docker run --rm -p 5001:8080 \
  -e REVOLUTION_API_URL=https://your-evolution-api \
  -e REVOLUTION_API_KEY=your-key \
  -e OPENAI_API_KEY=sk-... \
  muskinho
```

Notes:

- The container runs **uvicorn** with `main:app` on port **8080** (map to host as above).
- Configure your Evolution API instance webhook to `https://<your-host>/webhook/messages-upsert`.

## Project layout

- `main.py` — FastAPI app, Evolution API webhook, terminal chat
- `openai_client.py` — Unified AI client (OpenAI, Grok, Gemini, Ollama)
- `personality.py` — System prompt / persona
- `schema.py` — Webhook payload models
- `utils.py` — Conversation history, response shortener, WhatsApp send
