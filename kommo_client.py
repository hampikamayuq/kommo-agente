import logging
import time
import httpx
from config import Settings

logger = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None


def init(s: Settings) -> None:
    global _client
    _client = httpx.AsyncClient(
        base_url=f"https://{s.KOMMO_SUBDOMAIN}.kommo.com",
        headers={"Authorization": f"Bearer {s.KOMMO_API_TOKEN}"},
        timeout=30.0,
    )


async def close() -> None:
    global _client
    if _client:
        await _client.aclose()
        _client = None


def _check() -> httpx.AsyncClient:
    if _client is None:
        raise RuntimeError("Kommo client not initialized")
    return _client


async def add_note(lead_id: str, text: str, note_type: int = 10) -> dict:
    client = _check()
    payload = [{"note_type": note_type, "params": {"text": text}}]
    resp = await client.post(f"/api/v4/leads/{lead_id}/notes", json=payload)
    if resp.status_code == 401:
        logger.error("Kommo 401 Unauthorized — verifique KOMMO_API_TOKEN")
    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        logger.error("add_note error %s: %s", e.response.status_code, e.response.text)
        raise
    return resp.json()


async def create_task(lead_id: str, text: str, complete_till: int | None = None) -> dict:
    client = _check()
    if complete_till is None:
        complete_till = int(time.time()) + 3600
    payload = [
        {
            "task_type_id": 1,
            "text": text,
            "complete_till": complete_till,
            "entity_id": int(lead_id),
            "entity_type": "leads",
        }
    ]
    resp = await client.post("/api/v4/tasks", json=payload)
    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        logger.error("create_task error %s: %s", e.response.status_code, e.response.text)
        raise
    return resp.json()


async def update_lead(lead_id: str, *, tags: list[str] | None = None, stage_id: int | None = None) -> dict:
    client = _check()
    payload: dict = {}
    if tags:
        payload["_embedded"] = {"tags": [{"name": t} for t in tags]}
    if stage_id is not None:
        payload["status_id"] = stage_id
    if not payload:
        return {}
    resp = await client.patch(f"/api/v4/leads/{lead_id}", json=payload)
    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        logger.error("update_lead error %s: %s", e.response.status_code, e.response.text)
        raise
    return resp.json()


async def send_message(lead_id: str, text: str) -> dict:
    """Send a reply visible to the patient. Falls back to add_note if direct send fails."""
    client = _check()
    resp = await client.post(
        f"/api/v4/leads/{lead_id}/messages",
        json={"text": text},
    )
    if resp.status_code in (404, 405, 422):
        logger.warning("send_message not supported for lead %s, falling back to note", lead_id)
        return await add_note(lead_id, text, note_type=4)
    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        logger.error("send_message error %s: %s", e.response.status_code, e.response.text)
        return await add_note(lead_id, text, note_type=4)
    return resp.json()
