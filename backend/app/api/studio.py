"""AG Studio AI assistant backend: one LLM turn per request, plus the console's Studio config.

Studio bundles no LLM; the browser-side AgLlmAdapter posts each turn here in a provider-neutral shape and gets the
assistant turn back. The Anthropic key never leaves the server. Tools run in the browser (Studio executes them),
so this endpoint only relays tool definitions, calls and results.

Neutral wire shape (request, optionally gzip+base64 wrapped as {"gzip_b64": "..."} to fit the proxy body cap):
  {"system": str, "messages": [{"role": "user"|"assistant", "content": [Block]}], "tools": [{name, description,
   parameters}]}
  Block = {"type": "text", "text"} | {"type": "tool_call", "id", "name", "input"}
        | {"type": "tool_result", "tool_call_id", "output", "is_error"}
Response: {"data": {"id", "model", "stop_reason", "content": [text|tool_call Block], "usage", "error"}}
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import os
import re
import zlib
from functools import lru_cache
from pathlib import Path
from typing import Literal

import anthropic
from dotenv import dotenv_values
from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError

from app.api.routes import operator
from app.config import get_settings

router = APIRouter(prefix="/api/v1/studio")
log = logging.getLogger(__name__)

ROOT_ENV = Path(__file__).resolve().parents[3] / ".env"
MAX_TOKENS = 16000
MAX_COMPRESSED_B64 = 64 * 1024
MAX_DECOMPRESSED = 1024 * 1024
_UNSAFE_ID = re.compile(r"[^A-Za-z0-9_-]")


class Block(BaseModel):
    type: Literal["text", "tool_call", "tool_result"]
    text: str | None = Field(None, max_length=200_000)
    id: str | None = Field(None, max_length=128)
    name: str | None = Field(None, max_length=128)
    input: dict | None = None
    tool_call_id: str | None = Field(None, max_length=128)
    output: str | None = Field(None, max_length=200_000)
    is_error: bool = False


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: list[Block] = Field(min_length=1, max_length=60)


class ToolDef(BaseModel):
    name: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    description: str = Field(max_length=10_000)
    parameters: dict


class LlmTurnIn(BaseModel):
    system: str = Field("", max_length=200_000)
    messages: list[Message] = Field(min_length=1, max_length=60)
    tools: list[ToolDef] = Field(default_factory=list, max_length=40)


def _bad(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, detail={"code": code, "message": message})


def _decode(body: dict) -> LlmTurnIn:
    if "gzip_b64" in body:
        packed = body["gzip_b64"]
        if not isinstance(packed, str) or len(packed) > MAX_COMPRESSED_B64:
            raise _bad(413, "BODY_TOO_LARGE", "compressed body too large")
        try:
            inflater = zlib.decompressobj(wbits=31)
            raw = inflater.decompress(base64.b64decode(packed, validate=True), MAX_DECOMPRESSED + 1)
            if len(raw) > MAX_DECOMPRESSED or inflater.unconsumed_tail:
                raise _bad(413, "BODY_TOO_LARGE", "decompressed body too large")
            body = json.loads(raw)
        except (binascii.Error, zlib.error, ValueError) as e:
            raise _bad(400, "BAD_ENCODING", "body is not valid gzip+base64 JSON") from e
    try:
        return LlmTurnIn.model_validate(body)
    except ValidationError as e:
        raise HTTPException(422, detail=e.errors(include_url=False, include_context=False, include_input=False)) from e


def _safe_id(raw: str | None) -> str:
    return _UNSAFE_ID.sub("_", raw or "")[:64] or "call"


def _to_anthropic_block(b: Block) -> dict | None:
    if b.type == "text":
        return {"type": "text", "text": b.text} if b.text else None
    if b.type == "tool_call":
        return {"type": "tool_use", "id": _safe_id(b.id), "name": b.name or "unknown", "input": b.input or {}}
    return {"type": "tool_result", "tool_use_id": _safe_id(b.tool_call_id), "content": b.output or "",
            "is_error": b.is_error}


def _to_anthropic_messages(messages: list[Message]) -> list[dict]:
    out = []
    for m in messages:
        blocks = [x for x in (_to_anthropic_block(b) for b in m.content) if x]
        if blocks:
            out.append({"role": m.role, "content": blocks})
    if not out or out[0]["role"] != "user":
        out.insert(0, {"role": "user", "content": [{"type": "text", "text": "(conversation start)"}]})
    return out


def _from_anthropic(resp) -> dict:
    content = []
    for b in resp.content:
        if b.type == "text" and b.text:
            content.append({"type": "text", "text": b.text})
        elif b.type == "tool_use":
            content.append({"type": "tool_call", "id": b.id, "name": b.name, "input": dict(b.input or {})})
    error = None
    if resp.stop_reason == "refusal":
        content = [{"type": "text", "text": "The model declined this request. Try rephrasing it."}]
        error = {"code": "REFUSAL", "message": "model refused"}
    return {"id": resp.id, "model": resp.model, "stop_reason": resp.stop_reason, "content": content,
            "usage": {"input_tokens": resp.usage.input_tokens or 0, "output_tokens": resp.usage.output_tokens or 0},
            "error": error}


@lru_cache
def _client(api_key: str) -> anthropic.Anthropic:
    # The console proxy gives up after 90 s, so do not outlive it.
    return anthropic.Anthropic(api_key=api_key, max_retries=1, timeout=85.0)


@router.post("/llm")
def llm_turn(body: dict = Body(...), _actor: str = Depends(operator)):
    req = _decode(body)
    cfg = get_settings()
    if not cfg.anthropic_api_key:
        raise _bad(503, "LLM_NOT_CONFIGURED", "ANTHROPIC_API_KEY is not configured on the server")
    tools = [{"name": t.name, "description": t.description, "input_schema": {"type": "object", **t.parameters}}
             for t in req.tools]
    kwargs = {"tools": tools} if tools else {}  # never tool_choice any/tool: rejected by this model
    try:
        resp = _client(cfg.anthropic_api_key).messages.create(
            model=cfg.anthropic_model, max_tokens=MAX_TOKENS, system=req.system or anthropic.NOT_GIVEN,
            messages=_to_anthropic_messages(req.messages), output_config={"effort": cfg.anthropic_effort}, **kwargs)
    except anthropic.APIError as e:
        log.warning("studio llm turn failed: %s", type(e).__name__)
        raise _bad(502, "LLM_UNAVAILABLE", "The language model request failed. Try again shortly.") from e
    return {"data": _from_anthropic(resp)}


def _env(key: str) -> str | None:
    return os.environ.get(key) or dotenv_values(ROOT_ENV).get(key) or None


@router.get("/config")
def studio_config(_actor: str = Depends(operator)):
    # AG licence keys are designed to be public client-side; the Anthropic key never appears here.
    ai_flag = (_env("STUDIO_AI") or "1") != "0"
    return {"data": {"license_key": _env("AG_STUDIO_LICENSE_KEY") or _env("NEXT_PUBLIC_AG_STUDIO_LICENSE_KEY"),
                     "ai_enabled": ai_flag and bool(get_settings().anthropic_api_key),
                     "model": get_settings().anthropic_model}}
