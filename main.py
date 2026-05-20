import hashlib
import logging
import time
from contextlib import asynccontextmanager
from typing import Annotated

import kommo_client
from agent import process_message
from config import settings
from conversation import (
    close_db,
    get_lead_state,
    init_db,
    set_lead_state,
    should_resume,
)

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# Deduplication: (lead_id, text_hash, minute) — capped at 500 entries
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
    logger.info("Agent started — provider: %s | bot_user_id: %s", settings.AI_PROVIDER, settings.KOMMO_BOT_USER_ID)
    yield
    await close_db()
    await kommo_client.close()
    logger.info("Agent stopped")


app = FastAPI(title="Kommo AI Agent — Clínica Qara", lifespan=lifespan)


# ── Event handlers (observer pattern, one per event type) ─────────────────────

async def _handle_new_message(data: dict) -> dict:
    lead_id = data.get("message[add][0][element_id]", "").strip()
    if not lead_id:
        return {"status": "ignored", "reason": "no_lead_id"}

    element_type = data.get("message[add][0][element_type]", "0")
    if element_type != "1":
        return {"status": "ignored", "reason": "not_lead"}

    created_by = data.get("message[add][0][created_by]", "1")

    # ── Kommo SalesBot sent a message → pause AI, update bot timestamp ──────
    if created_by == settings.KOMMO_BOT_USER_ID:
        await set_lead_state(lead_id, "bot_scheduling")
        logger.info("Lead %s: Kommo bot active → agent paused", lead_id)
        return {"status": "ignored", "reason": "bot_message"}

    # ── Human staff sent a message → pause AI ───────────────────────────────
    if created_by != "0":
        await set_lead_state(lead_id, "paused_human")
        logger.info("Lead %s: human staff (user %s) → agent paused", lead_id, created_by)
        return {"status": "ignored", "reason": "staff_message"}

    # ── Patient message ──────────────────────────────────────────────────────
    user_text = data.get("message[add][0][text]", "").strip()
    if not user_text:
        return {"status": "ignored", "reason": "empty_text"}

    if _is_duplicate(lead_id, user_text):
        logger.info("Duplicate message skipped for lead %s", lead_id)
        return {"status": "ignored", "reason": "duplicate"}

    # Check lead state — auto-resume if timeout has elapsed
    state = await get_lead_state(lead_id)
    if state != "active":
        if await should_resume(lead_id):
            await set_lead_state(lead_id, "active")
            logger.info("Lead %s: auto-resumed from '%s'", lead_id, state)
        else:
            logger.info("Lead %s: agent is '%s' — ignoring patient message", lead_id, state)
            return {"status": "ignored", "reason": f"agent_{state}"}

    logger.info("Processing message for lead %s: %s", lead_id, user_text[:80])
    result = await process_message(lead_id, user_text, settings)

    # Send reply to patient
    await kommo_client.send_message(lead_id, result["message"])

    # Apply Kommo actions from AI response
    kommo = result.get("kommo", {})

    if kommo.get("notes"):
        await kommo_client.add_note(lead_id, kommo["notes"], note_type=10)

    tags = list(kommo.get("tags") or [])
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
    logger.info("New lead %s", lead_id)
    # Welcome is sent by the Kommo SalesBot flow — no need to send here.
    # Just ensure the lead starts in active state.
    await set_lead_state(lead_id, "active")
    return {"status": "ok", "event": "new_lead"}


async def _handle_status_change(data: dict) -> dict:
    lead_id = data.get("leads[status][0][id]", "").strip()
    if not lead_id:
        return {"status": "ignored"}
    new_status = data.get("leads[status][0][status_id]", "")
    logger.info("Lead %s status → %s", lead_id, new_status)
    # If you know the "Agendado" stage ID, add it here:
    # if new_status == settings.KOMMO_SCHEDULED_STAGE_ID:
    #     await set_lead_state(lead_id, "active")
    return {"status": "ok", "event": "status_change"}


# ── Webhook endpoint ───────────────────────────────────────────────────────────

@app.post("/webhook")
async def webhook(request: Request) -> JSONResponse:
    try:
        form = await request.form()
        data = dict(form)

        if settings.WEBHOOK_SECRET and data.get("secret") != settings.WEBHOOK_SECRET:
            return JSONResponse({"status": "forbidden"}, status_code=403)

        # Route by event type (observer pattern)
        if "message[add][0][text]" in data or "message[add][0][element_id]" in data:
            result = await _handle_new_message(data)
        elif "leads[add][0][id]" in data:
            result = await _handle_new_lead(data)
        elif "leads[status][0][id]" in data:
            result = await _handle_status_change(data)
        else:
            logger.debug("Unknown webhook event keys: %s", list(data.keys())[:5])
            result = {"status": "ignored", "reason": "unknown_event"}

        return JSONResponse(result)

    except Exception:
        logger.exception("Unhandled error in webhook")
        return JSONResponse({"status": "error"})  # Always 200 to stop Kommo retries


# ── /send endpoint (inspired by open-wa Easy API) ─────────────────────────────

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


# ── /resume endpoint — manual override to reactivate agent ────────────────────

@app.post("/resume/{lead_id}")
async def resume(
    lead_id: str,
    x_api_key: Annotated[str | None, Header()] = None,
) -> dict:
    if settings.API_KEY and x_api_key != settings.API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    old_state = await get_lead_state(lead_id)
    await set_lead_state(lead_id, "active")
    logger.info("Lead %s manually resumed from '%s'", lead_id, old_state)
    return {"status": "ok", "lead_id": lead_id, "previous_state": old_state}


# ── /pause endpoint — manual override to pause agent ──────────────────────────

@app.post("/pause/{lead_id}")
async def pause(
    lead_id: str,
    x_api_key: Annotated[str | None, Header()] = None,
) -> dict:
    if settings.API_KEY and x_api_key != settings.API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    await set_lead_state(lead_id, "paused_human")
    logger.info("Lead %s manually paused", lead_id)
    return {"status": "ok", "lead_id": lead_id, "state": "paused_human"}


# ── Health check ───────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "provider": settings.AI_PROVIDER,
        "kommo_subdomain": settings.KOMMO_SUBDOMAIN or "not_set",
        "bot_user_id": settings.KOMMO_BOT_USER_ID,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=settings.PORT, workers=1)
