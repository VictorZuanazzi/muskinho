# Muskinho WhatsApp Bot

Flask backend that connects Twilio WhatsApp to an AI chat persona. Twilio posts inbound messages to `/webhook`; the app replies via Twilio and exposes `/test` for local exercise.

## Configuration
- `OPENAI_API_KEY` (required) and optional `OPENAI_MODEL`, `OPENAI_BASE_URL`
- `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_NUMBER`
- `PORT` (default `5001`), `DEBUG` (default `False`)
- Optional: `LOG_FILE` to override rotating log path (defaults under `logs/`)
- Optional Ollama: set `OPENAI_MODEL=ollama:llama3` and `OPENAI_BASE_URL=http://host.docker.internal:11434/v1/chat/completions` when running the container on a host with Ollama.

## Run with Docker
```bash
docker build -t muskinho .
docker run --rm -p 5001:5001 \
  -e OPENAI_API_KEY=sk-... \
  -e TWILIO_ACCOUNT_SID=AC... \
  -e TWILIO_AUTH_TOKEN=... \
  -e TWILIO_WHATSAPP_NUMBER=whatsapp:+1415523XXXX \
  muskinho
```

Notes:
- The container boots via Gunicorn using `app:create_app` and respects `PORT`, `WORKERS`, `TIMEOUT`.
- Update your Twilio WhatsApp sandbox/number webhook to `https://<host>/webhook`.
- You can dry-run without Twilio:  
  `curl -X POST http://localhost:5001/test -H "Content-Type: application/json" -d '{"message":"oi","phone":"local"}'`
