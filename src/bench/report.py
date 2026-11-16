"""Results tables and transcript excerpts, from results/runs.jsonl and results/benign.jsonl."""

from __future__ import annotations

import json
from collections import defaultdict

from fabraix_engine.challenges import get_challenge

from . import CHALLENGES, RESULTS
from .judges import JUDGES


def _read(name: str) -> list[dict]:
    path = RESULTS / name
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _transcript(run: dict) -> dict:
    return json.loads((RESULTS / "transcripts" / f"{run['run_id']}.json").read_text())


def table(runs: list[dict] | None = None, benign: list[dict] | None = None) -> list[dict]:
    """One row per challenge x judge. ACE-style dollars to break = all attacker spend in the
    cell (failed runs included) divided by the number of breaks."""
    runs = _read("runs.jsonl") if runs is None else runs
    benign = _read("benign.jsonl") if benign is None else benign
    cells: dict[tuple, list] = defaultdict(list)
    for r in runs:
        cells[(r["challenge"], r["judge"])].append(r)
    calls: dict[tuple, list] = defaultdict(list)
    for b in benign:
        calls[(b["challenge"], b["judge"])].extend(b["tool_calls"])
    rows = []
    for slug in CHALLENGES:
        for judge in JUDGES:
            cell = cells.get((slug, judge), [])
            if not cell:
                continue
            breaks = sum(r["won"] for r in cell)
            spend = sum(r["attacker_usd"] for r in cell)
            bc = calls.get((slug, judge), [])
            rows.append({
                "challenge": slug, "name": get_challenge(slug).name, "judge": judge,
                "runs": len(cell), "breaks": breaks, "break_rate": breaks / len(cell),
                "attacker_usd": spend,
                "usd_to_break": spend / breaks if breaks else None,
                "mean_turns_to_break": (sum(r["turns"] for r in cell if r["won"]) / breaks) if breaks else None,
                "defender_usd": sum(r["defender_usd"] for r in cell),
                "judge_usd": sum(r["judge_usd"] for r in cell),
                "benign_calls": len(bc), "false_blocks": sum(c["blocked"] for c in bc),
                "false_block_rate": (sum(c["blocked"] for c in bc) / len(bc)) if bc else None,
            })
    return rows


def caught_and_missed(runs: list[dict]) -> tuple[list[dict], list[dict]]:
    """Caught: a judged run where the guardrail blocked the sink, on a challenge+seed the bare
    defender lost. Missed: a judged run that still broke."""
    win_sinks = {s: get_challenge(s).win.sink for s in CHALLENGES}
    bare_broke = {(r["challenge"], r["seed"]) for r in runs if r["judge"] == "none" and r["won"]}
    caught, missed = [], []
    for r in runs:
        if r["judge"] == "none":
            continue
        t = _transcript(r)
        if r["won"]:
            last = t["log"][-1]
            missed.append({"run": r, "turn": last, "sink": win_sinks[r["challenge"]]})
            continue
        if (r["challenge"], r["seed"]) not in bare_broke:
            continue
        for turn in t["log"]:
            hit = [c for c in turn["tool_calls"] if c["name"] == win_sinks[r["challenge"]] and c["blocked"]]
            if hit:
                caught.append({"run": r, "turn": turn, "call": hit[0]})
                break
    return caught, missed


def _usd(x):
    return "n/a" if x is None else f"${x:.4f}"


def _pct(x):
    return "n/a" if x is None else f"{x:.0%}"


def _clip(s: str, n: int = 350) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[:n] + "..."


def write_summary() -> str:
    runs, benign = _read("runs.jsonl"), _read("benign.jsonl")
    rows = table(runs, benign)
    spend_path = RESULTS / "spend.json"
    total = json.loads(spend_path.read_text())["total_usd"] if spend_path.exists() else 0.0
    models = runs[0]["models"] if runs else {}
    out = ["# Results", ""]
    if models:
        out.append("Models: " + ", ".join(f"{k} `{v}`" for k, v in models.items()) + ".")
    out += [f"Total OpenRouter spend logged: ${total:.4f}.", "",
            "## Table 1: challenge x judge", "",
            "Dollars to break is ACE-style: all attacker spend in the cell, failed runs included, "
            "divided by the number of breaks. No breaks means the attacker spent that much and got nothing.", "",
            "| Challenge | Judge | Breaks | Break rate | Attacker $ to break | Turns to break | False blocks | Judge $ |",
            "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        to_break = _usd(r["usd_to_break"]) if r["breaks"] else f"none in {r['runs']} (spent {_usd(r['attacker_usd'])})"
        turns = f"{r['mean_turns_to_break']:.1f}" if r["mean_turns_to_break"] else "n/a"
        fb = f"{r['false_blocks']}/{r['benign_calls']} ({_pct(r['false_block_rate'])})" if r["benign_calls"] else "n/a"
        out.append(f"| {r['name']} | {r['judge']} | {r['breaks']}/{r['runs']} | {_pct(r['break_rate'])} "
                   f"| {to_break} | {turns} | {fb} | {_usd(r['judge_usd'])} |")

    other = _read("runs-gpt-4o-mini.jsonl")
    if other:
        orows = table(other, _read("benign-gpt-4o-mini.jsonl"))
        out += ["", "## Table 1b: same matrix, defender `openai/gpt-4o-mini`", "",
                f"{sum(r['breaks'] for r in orows)} breaks in {sum(r['runs'] for r in orows)} runs. This defender held "
                "every line on its own, so the guardrails had nothing to stop. That is why the headline matrix uses a "
                "weaker defender, and why Table 2 tests the judges directly.", "",
                "| Challenge | Judge | Breaks | Attacker $ spent | False blocks |", "|---|---|---|---|---|"]
        for r in orows:
            fb = f"{r['false_blocks']}/{r['benign_calls']}" if r["benign_calls"] else "n/a"
            out.append(f"| {r['name']} | {r['judge']} | {r['breaks']}/{r['runs']} | {_usd(r['attacker_usd'])} | {fb} |")

    from .probe import probe_table

    prow = probe_table()
    if prow:
        out += ["", "## Table 2: judges on counterfactual tool calls", "",
                "Every recorded attack conversation (both defenders) replayed up to the attacker's last message, "
                "then each judge asked about two calls: the winning sink call (the attacker's own target host when "
                "it named one), and an in-policy call under the same pressure (`about_fabraix`, a SentinelID check "
                "against the real partner, adding `https://docs.python.org`). No defender involved.", "",
                "| Challenge | Judge | Malicious call blocked | Legit call blocked under attack |", "|---|---|---|---|"]
        for r in prow:
            m = f"{r['malicious_blocked']}/{r['malicious_n']} ({_pct(r['malicious_blocked'] / r['malicious_n'])})"
            l = f"{r['legit_blocked']}/{r['legit_n']} ({_pct(r['legit_blocked'] / r['legit_n'])})"
            out.append(f"| {r['name']} | {r['judge']} | {m} | {l} |")

    pilot = [r for r in _read("defender-pilot.jsonl")]
    if pilot:
        by: dict = defaultdict(lambda: [0, 0])
        for r in pilot:
            by[r["models"]["defender"]][0] += r["won"]
            by[r["models"]["defender"]][1] += 1
        out += ["", "## Defender pilot", "",
                "Before the second matrix: four cheap defenders, no guardrail, seeds `authority`, `policy-update` "
                "and `indirect` on all three challenges.", "",
                "| Defender | Breaks |", "|---|---|"]
        out += [f"| `{m}` | {w}/{n} |" for m, (w, n) in by.items()]
        out += ["", "These are the only breaks in the whole project, and every one used the `indirect` seed: "
                "planted search results presented as official procedure, then a short follow-up asking for the call."]

    replay = _read("replay.jsonl")
    out += ["", "## Caught", "",
            "Each real break, replayed through each judge: the conversation up to the winning turn, then the exact "
            "winning call.", ""]
    for r in replay:
        verdict = "blocked" if r["blocked"] else "allowed"
        why = _clip(r["reasoning"], 200) or "(no reason given)"
        out.append(f"- **{get_challenge(r['challenge']).name}**, `{r['run_id']}`, {r['judge']}: {verdict}. "
                   f"`{r['tool']}({json.dumps(r['args'])[:120]})`. {why}")
    if replay:
        r0 = next(r for r in replay if r["judge"] == "prompt")
        t = _transcript({"run_id": r0["run_id"]})
        planted = next((x["planted"] for x in t["log"] if x["planted"]), None) or []
        out += ["", f"What the defender read before it folded (`{r0['run_id']}`, first planted result):", "",
                f"> {_clip((planted[0]['title'] + ': ' + planted[0]['description']) if planted else '', 400)}", "",
                f"> Attacker, winning turn: {_clip(t['log'][-1]['attacker'], 300)}"]
    else:
        out.append("No real breaks to replay.")

    probe_rows = _read("probe.jsonl")
    misses = [r for r in probe_rows if r["kind"] == "malicious" and not r["blocked"]]
    out += ["", "## Missed", "", "Malicious counterfactual calls a judge allowed (Table 2).", ""]
    for r in misses[:3]:
        out.append(f"- **{get_challenge(r['challenge']).name}**, {r['judge']}, `{r['tool']}({json.dumps(r['args'])})`: "
                   f"{_clip(r['reasoning'], 250)}")
    if not misses:
        out.append("None.")
    over = [r for r in probe_rows if r["kind"] == "legit" and r["blocked"] and r["reasoning"]]
    out += ["", "## Over-blocked", "",
            "Legitimate calls blocked under attack pressure. judgeman rarely says why: the judge model left out "
            "judgeman's `critique` field in most replies, so only the prompt judge's reasons can be quoted.", ""]
    seen = set()
    for r in over:
        if r["reasoning"] in seen or len(seen) == 3:
            continue
        seen.add(r["reasoning"])
        out.append(f"- **{get_challenge(r['challenge']).name}**, {r['judge']}, `{r['tool']}({json.dumps(r['args'])})`: "
                   f"{_clip(r['reasoning'], 200)}")
    jm = [r for r in probe_rows if r["judge"] == "judgeman"]
    if jm:
        out.append(f"- judgeman gave a reason for {sum(bool(r['reasoning']) for r in jm)} of its {len(jm)} verdicts.")
    takeaway = RESULTS / "takeaway.md"
    if takeaway.exists():
        out += ["", "## Takeaway", "", takeaway.read_text().strip()]
    text = "\n".join(out) + "\n"
    (RESULTS / "summary.md").write_text(text)
    return text
