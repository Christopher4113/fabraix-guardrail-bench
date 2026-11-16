"""Local implementations of the six Platform seams, plus the spend ledger.

LLM calls go straight to OpenRouter over httpx (already an engine dependency) instead of
litellm, because OpenRouter reports the billed cost of each call in `usage.cost`.
"""

from __future__ import annotations

import json
import os
import asyncio
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

from fabraix_engine.adapters.base import GuardrailDecision, LlmResult, Platform

from . import RESULTS

OPENROUTER = "https://openrouter.ai/api/v1"


def model_for(role: str) -> str:
    defaults = {
        "defender": "mistralai/mistral-small-3.2-24b-instruct",
        "attacker": "deepseek/deepseek-chat-v3.1",
        "judge": "google/gemini-2.5-flash-lite",
    }
    return os.environ.get(f"BENCH_{role.upper()}_MODEL", defaults[role])


# ---------------------------------------------------------------------------
# Spend ledger: every dollar, by role, with a hard cap that survives restarts
# ---------------------------------------------------------------------------
class BudgetExceeded(Exception):
    pass


class Ledger:
    """Total spend is persisted in results/spend.json so separate runs share one cap."""

    def __init__(self, cap: float | None = None, path=RESULTS / "spend.json"):
        self.cap = cap if cap is not None else float(os.environ.get("BENCH_BUDGET_USD", "15"))
        self.path = path
        self.lock = threading.Lock()
        self.total = json.loads(path.read_text())["total_usd"] if path.exists() else 0.0

    def check(self) -> None:
        if self.total >= self.cap:
            raise BudgetExceeded(f"spent ${self.total:.4f} of ${self.cap:.2f} cap")

    def charge(self, usd: float, run: "RunCost | None", role: str) -> None:
        with self.lock:
            self.total += usd
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"total_usd": round(self.total, 6)}))
        if run is not None:
            run.add(role, usd)


@dataclass
class RunCost:
    attacker: float = 0.0
    defender: float = 0.0
    judge: float = 0.0
    calls: list[dict] = field(default_factory=list)

    def add(self, role: str, usd: float) -> None:
        setattr(self, role, getattr(self, role) + usd)


# ---------------------------------------------------------------------------
# Raw OpenRouter call, shared by defender, attacker and prompt judge
# ---------------------------------------------------------------------------
_pricing: dict[str, tuple[float, float]] = {}


def _price(model: str, usage: dict) -> float:
    """Fallback when a response carries no usage.cost: list price x tokens."""
    if not _pricing:
        for m in httpx.get(f"{OPENROUTER}/models", timeout=30).json()["data"]:
            _pricing[m["id"]] = (float(m["pricing"]["prompt"]), float(m["pricing"]["completion"]))
    p_in, p_out = _pricing.get(model, (0.0, 0.0))
    return usage.get("prompt_tokens", 0) * p_in + usage.get("completion_tokens", 0) * p_out


async def chat(
    *,
    model: str,
    messages: list[dict],
    ledger: Ledger,
    run: RunCost | None,
    role: str,
    tools: list[dict] | None = None,
    json_mode: bool = False,
    max_tokens: int = 1200,
) -> dict:
    """One completion. Returns the OpenRouter message dict plus `usage`. Charges the ledger."""
    ledger.check()
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise SystemExit("OPENROUTER_API_KEY is not set. Copy .env.example to .env and add it.")
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.7 if role == "attacker" else 0,
        "usage": {"include": True},
    }
    if tools:
        body["tools"] = tools
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    async with httpx.AsyncClient(timeout=120) as client:
        for attempt in range(6):
            r = await client.post(
                f"{OPENROUTER}/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json=body,
            )
            if r.status_code not in (429, 500, 502, 503) or attempt == 5:
                break
            await asyncio.sleep(2 ** attempt)
    if r.status_code in (402, 403):
        raise BudgetExceeded(f"OpenRouter refused the call ({r.status_code}): {r.text[:200]}")
    r.raise_for_status()
    data = r.json()
    if "choices" not in data:
        raise RuntimeError(f"OpenRouter error: {str(data)[:300]}")
    usage = data.get("usage") or {}
    cost = usage.get("cost")
    cost = float(cost) if cost is not None else _price(model, usage)
    ledger.charge(cost, run, role)
    if run is not None:
        run.calls.append({"role": role, "model": model, "usd": cost,
                          "in": usage.get("prompt_tokens"), "out": usage.get("completion_tokens")})
    msg = data["choices"][0]["message"]
    msg["usage"] = usage
    return msg


# ---------------------------------------------------------------------------
# The six seams
# ---------------------------------------------------------------------------
class MemoryStore:
    def __init__(self):
        self.sessions: dict[str, dict] = {}
        self.messages: dict[str, list[dict]] = {}

    async def create_session(self, *, guardrails_run_id, challenge_slug, user_identifier,
                             agent_model, guardrails_model, browser_model):
        sid = str(uuid.uuid4())
        self.sessions[sid] = {"id": sid, "challenge_slug": challenge_slug, "agent_model": agent_model,
                              "guardrails_model": guardrails_model, "message_count": 0,
                              "solved_at": None, "ended_at": None}
        self.messages[sid] = []
        return self.sessions[sid]

    async def get_session(self, session_id):
        return self.sessions.get(session_id)

    async def mark_session_solved(self, session_id):
        s = self.sessions[session_id]
        first = s["solved_at"] is None
        s["solved_at"] = s["solved_at"] or time.time()
        return first

    async def mark_session_ended(self, session_id):
        self.sessions[session_id]["ended_at"] = time.time()

    async def touch_session(self, session_id):
        self.sessions[session_id]["message_count"] += 1

    async def add_message(self, *, session_id, role, content, tools, thinking=None):
        m = {"role": role, "content": content, "tools": tools, "created_at": time.time()}
        self.messages[session_id].append(m)
        return m

    async def get_messages(self, session_id):
        return list(self.messages.get(session_id, []))

    # the leaderboard is never used locally
    async def get_leaderboard_entry(self, session_id):
        return None

    async def add_leaderboard_entry(self, *, session_id, challenge_slug, profile_id, time_seconds):
        return {}


class SilentNotifier:
    async def notify_win(self, *, challenge_slug, display_name):
        pass


class OpenRouterLlm:
    """The engine's Llm seam. Every call it makes is charged to the defender."""

    def __init__(self, ledger: Ledger, run: RunCost | None):
        self.ledger, self.run = ledger, run

    async def complete(self, *, model, system, messages, tools):
        msg = await chat(model=model, messages=[{"role": "system", "content": system}, *messages],
                         tools=tools, ledger=self.ledger, run=self.run, role="defender")
        calls = []
        for tc in msg.get("tool_calls") or []:
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append({"id": tc.get("id"), "name": tc["function"]["name"],
                          "arguments": args if isinstance(args, dict) else {}})
        usage = msg["usage"]
        return LlmResult(content=msg.get("content") or "", tool_calls=calls,
                         input_tokens=usage.get("prompt_tokens", 0),
                         output_tokens=usage.get("completion_tokens", 0))


class DisabledBrowser:
    async def run(self, *, task, return_type):
        return "The browser is disabled in the local bench."


@dataclass
class LocalSettings:
    slug: str
    guardrails_enabled: bool
    agent_model: str = field(default_factory=lambda: model_for("defender"))
    guardrails_model: str | None = field(default_factory=lambda: model_for("judge"))
    browser_model: str | None = None
    browser_agent_enabled: bool = False

    def secret_for(self, challenge_slug: str) -> str:
        return f"LOCAL-SECRET-{challenge_slug}"


class AllowAll:
    """The judge seam's floor. Also what NoJudge is."""

    async def check_action(self, *, session_id, trace_id, tool_name, tool_args, context):
        return GuardrailDecision(blocked=False, reasoning="no guardrail")

    async def log_event(self, *, trace_id, event, data):
        pass


def make_platform(slug, judge, ledger, run, store=None, llm=None) -> Platform:
    return Platform(
        store=store or MemoryStore(),
        guardrail=judge,
        notifier=SilentNotifier(),
        llm=llm or OpenRouterLlm(ledger, run),
        settings=LocalSettings(slug=slug, guardrails_enabled=not isinstance(judge, AllowAll)),
        browser=DisabledBrowser(),
    )
