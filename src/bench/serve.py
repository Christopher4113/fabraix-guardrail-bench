"""Demo server: stdlib only. Serves ui.html, the results, and a live attack stream (SSE)."""

from __future__ import annotations

import asyncio
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from fabraix_engine.challenges import get_challenge

from . import CHALLENGES, RESULTS
from .adapters import Ledger, model_for
from .attacker import SEEDS, run_attack
from .judges import JUDGES
from .probe import probe_table
from .report import _read, table

UI = Path(__file__).with_name("ui.html")
ledger = Ledger()  # one ledger for the server, so live runs share the cap


def data() -> dict:
    runs = _read("runs.jsonl")
    return {
        "rows": table(runs, _read("benign.jsonl")),
        "runs": runs,
        "live": _read("live.jsonl")[-20:],
        "pilot": _read("defender-pilot.jsonl"),
        "baseline": table(_read("runs-gpt-4o-mini.jsonl"), _read("benign-gpt-4o-mini.jsonl")),
        "probe": probe_table(),
        "replay": _read("replay.jsonl"),
        "benign": _read("benign.jsonl"),
        "challenges": [{"slug": s, "name": get_challenge(s).name, "persona": get_challenge(s).agent_persona,
                        "subtitle": get_challenge(s).agent_subtitle, "objective": get_challenge(s).objective,
                        "sink": get_challenge(s).win.sink} for s in CHALLENGES],
        "judges": JUDGES, "seeds": list(SEEDS),
        "models": {r: model_for(r) for r in ("defender", "attacker", "judge")},
        "spend": ledger.total, "cap": ledger.cap,
        "has_key": bool(os.environ.get("OPENROUTER_API_KEY")),
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body: bytes, kind: str, code: int = 200):
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path == "/":
            return self._send(UI.read_bytes(), "text/html; charset=utf-8")
        if url.path == "/api/data":
            return self._send(json.dumps(data()).encode(), "application/json")
        if url.path == "/api/transcript":
            path = (RESULTS / "transcripts" / f"{q.get('id', '')}.json").resolve()
            if path.parent != (RESULTS / "transcripts").resolve() or not path.exists():
                return self._send(b'{"error": "not found"}', "application/json", 404)
            return self._send(path.read_bytes(), "application/json")
        if url.path == "/api/live":
            return self._live(q)
        self._send(b"not found", "text/plain", 404)

    def _live(self, q):
        if q.get("challenge") not in CHALLENGES or q.get("judge") not in JUDGES or q.get("seed") not in SEEDS:
            return self._send(b'{"error": "bad parameters"}', "application/json", 400)
        turns = max(1, min(int(q.get("turns", 6)), 10))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        def emit(event: dict):
            self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
            self.wfile.flush()

        try:
            asyncio.run(run_attack(q["challenge"], q["judge"], q["seed"], turns=turns,
                                   ledger=ledger, emit=emit, out="live"))
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:  # surface it in the UI instead of a dead stream
            try:
                emit({"type": "error", "message": str(e)[:300]})
            except OSError:
                pass


def serve(port: int) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"bench UI on http://127.0.0.1:{port}")
    server.serve_forever()
