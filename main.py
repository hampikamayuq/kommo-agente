import hashlib
import logging
import time
from contextlib import asynccontextmanager
from typing import Annotated

import kommo_client
from agent import process_message
from config import settings
from conversation import close_db, init_db

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# Simple deduplication: store (lead_id, text_hash, minute) to avoid double-processing
# on Kommo retries. Capped at 500 entries.
_seen: set[tuple[str, str, int]] = set()


def _is_duplicate(lead_id: str, text: str) -> bool:
    minute = int(time.time() // 60)
    key = (lead_id, hashlib.md5(text.encode()).hexdigest(), minute)
    if key in _seen:
        return True
    _seen.add(key)
    if len(_seen) > 500:
        _seen.clear()
    return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    kommo_client.init(settings)
    logger.info("Agent started — provider: %s", settings.AI_PROVIDER)
    yield
    await close_db()
    await kommo_client.close()
    logger.info("Agent stopped")


app = FastAPI(title="Kommo AI Agent — Clínica Qara", lifespan=lifespan)


# ── Event handlers (observer pattern, one function per event type) ─────────────

async def _handle_new_message(data: dict) -> dict:
    created_by = data.get("message[add][0][created_by]", "1")
    if created_by != "0":
        return {"status": "ignored", "reason": "staff_message"}

    element_type = data.get("message[add][0][element_type]", "0")
    if element_type != "1":
        return {"status": "ignored", "reason": "not_lead"}

    lead_id = data.get("message[add][0][element_id]", "").strip()
    user_text = data.get("message[add][0][text]", "").strip()

    if not lead_id or not user_text:
        return {"status": "ignored", "reason": "empty"}

    if _is_duplicate(lead_id, user_text):
        logger.info("Duplicate message skipped for lead %s", lead_id)
        return {"status": "ignored", "reason": "duplicate"}

    logger.info("Processing message for lead %s: %s", lead_id, user_text[:80])
    result = await process_message(lead_id, user_text, settings)

    # Send reply to patient
    await kommo_client.send_message(lead_id, result["message"])

    # Apply Kommo actions from AI response
    kommo = result.get("kommo", {})

    if kommo.get("notes"):
        await kommo_client.add_note(lead_id, kommo["notes"], note_type=10)

    tags = kommo.get("tags") or []
    if kommo.get("handoff_human"):
        tags = list(set(tags + ["atendimento-humano"]))

    if tags:
        await kommo_client.update_lead(lead_id, tags=tags)

    if kommo.get("task"):
        await kommo_client.create_task(lead_id, kommo["task"])
    elif result.get("intent") == "agendamento":
        await kommo_client.create_task(lead_id, "Paciente solicitou agendamento — verificar agenda")
    elif result.get("intent") == "handoff" or kommo.get("handoff_human"):
        await kommo_client.create_task(lead_id, "⚠️ Encaminhar para atendimento humano urgente")

    return {"status": "ok", "intent": result.get("intent")}


async def _handle_new_lead(data: dict) -> dict:
    lead_id = data.get("leads[add][0][id]", "").strip()
    if not lead_id:
        return {"status": "ignored"}
    logger.info("New lead %s — sending welcome via note", lead_id)
    welcome = (
        "Olá! 👋 Eu sou a Tawany, assistente da Clínica Qara. "
        "Você prefere agendar consulta presencial ou teleconsulta, e qual é a sua principal queixa?"
    )
    await kommo_client.add_note(lead_id, welcome, note_type=4)
    return {"status": "ok", "event": "new_lead"}


async def _handle_status_change(data: dict) -> dict:
    lead_id = data.get("leads[status][0][id]", "").strip()
    if lead_id:
        logger.info("Lead %s status changed", lead_id)
    return {"status": "ok", "event": "status_change"}


# ── Webhook endpoint ────────────────────────────────────────────────────────────

@app.post("/webhook")
async def webhook(request: Request) -> JSONResponse:
    try:
        form = await request.form()
        data = dict(form)

        if settings.WEBHOOK_SECRET and data.get("secret") != settings.WEBHOOK_SECRET:
            return JSONResponse({"status": "forbidden"}, status_code=403)

        # Route to the correct handler based on event type (observer pattern)
        if "message[add][0][text]" in data:
            result = await _handle_new_message(data)
        elif "leads[add][0][id]" in data:
            result = await _handle_new_lead(data)
        elif "leads[status][0][id]" in data:
            result = await _handle_status_change(data)
        else:
            logger.debug("Unknown webhook event: %s", list(data.keys())[:5])
            result = {"status": "ignored", "reason": "unknown_event"}

        return JSONResponse(result)

    except Exception:
        logger.exception("Unhandled error in webhook")
        # Always return 200 so Kommo doesn't retry endlessly
        return JSONResponse({"status": "error"})


# ── /send endpoint (inspired by open-wa Easy API) ──────────────────────────────

class SendRequest(BaseModel):
    lead_id: str
    message: str


@app.post("/send")
async def send(
    body: SendRequest,
    x_api_key: Annotated[str | None, Header()] = None,
) -> dict:
    if settings.API_KEY and x_api_key != settings.API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    await kommo_client.send_message(body.lead_id, body.message)
    return {"status": "ok", "lead_id": body.lead_id}


# ── Health check ────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "provider": settings.AI_PROVIDER,
        "kommo_subdomain": settings.KOMMO_SUBDOMAIN or "not_set",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=settings.PORT, workers=1)
