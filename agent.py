import json
import logging
from typing import Any

from config import Settings
from conversation import get_history, add_message
from knowledge_base import get_relevant_context
from prompts import SYSTEM_PROMPT

logger = logging.getLogger(__name__)

# Lazy singletons — initialized on first use
_openai_client: Any = None
_anthropic_client: Any = None


def _get_openai(s: Settings):
    global _openai_client
    if _openai_client is None:
        import openai
        _openai_client = openai.AsyncOpenAI(api_key=s.OPENAI_API_KEY)
    return _openai_client


def _get_anthropic(s: Settings):
    global _anthropic_client
    if _anthropic_client is None:
        import anthropic
        _anthropic_client = anthropic.AsyncAnthropic(api_key=s.ANTHROPIC_API_KEY)
    return _anthropic_client


def _parse_response(raw: str) -> dict:
    text = raw.strip()
    # Strip markdown code fences (Anthropic sometimes adds them)
    if text.startswith("```"):
        parts = text.split("```")
        for part in parts:
            candidate = part.strip()
            if candidate.startswith("json"):
                candidate = candidate[4:].strip()
            if candidate.startswith("{"):
                text = candidate
                break
    try:
        result = json.loads(text)
        assert "message" in result and "intent" in result
        if "kommo" not in result:
            result["kommo"] = {"tags": [], "stage": None, "handoff_human": False, "task": None, "notes": None}
        return result
    except (json.JSONDecodeError, AssertionError, KeyError):
        logger.warning("Failed to parse AI JSON response, using fallback")
        return {
            "message": raw,
            "intent": "outro",
            "kommo": {"tags": [], "stage": None, "handoff_human": False, "task": None, "notes": None},
        }


def _build_system_prompt(user_text: str) -> str:
    """Append relevant KB sections to the base system prompt if found."""
    kb_context = get_relevant_context(user_text)
    if not kb_context:
        return SYSTEM_PROMPT
    return SYSTEM_PROMPT + f"\n\n## INFORMAÇÕES ADICIONAIS RELEVANTES\n{kb_context}"


async def process_message(lead_id: str, user_text: str, s: Settings) -> dict:
    history = await get_history(lead_id)
    messages = history + [{"role": "user", "content": user_text}]
    system = _build_system_prompt(user_text)

    raw_text: str
    if s.AI_PROVIDER == "openai":
        client = _get_openai(s)
        full_messages = [{"role": "system", "content": system}] + messages
        resp = await client.chat.completions.create(
            model=s.OPENAI_MODEL,
            messages=full_messages,
            response_format={"type": "json_object"},
            temperature=0.4,
            max_tokens=600,
        )
        raw_text = resp.choices[0].message.content or ""
    else:
        client = _get_anthropic(s)
        resp = await client.messages.create(
            model=s.ANTHROPIC_MODEL,
            system=system,
            messages=messages,
            max_tokens=600,
        )
        raw_text = resp.content[0].text if resp.content else ""

    result = _parse_response(raw_text)

    await add_message(lead_id, "user", user_text)
    await add_message(lead_id, "assistant", result["message"])

    return result
