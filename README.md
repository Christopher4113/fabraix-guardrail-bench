# fabraix-guardrail-bench

I got Fabraix's open-source Playground engine running locally and built a cheap multi-turn attacker
that breaks the published challenges while counting the dollars each break costs. Then I swapped
three guardrails into the engine's judge seam (none, a one-call prompt judge, and my own
[judgeman](https://github.com/Christopher4113/JudgeMan)) to see what each one blocks, what it
misses, and how much more a break costs with it in place.

## Results

Full tables and transcript excerpts: [results/summary.md](results/summary.md). The demo UI
(`uv run bench serve`) shows the same numbers, plus every transcript and a live run button.

<!-- results:start -->
Spend: $1.92 of the $15 cap, logged per call.

**Attack matrix.** 3 challenges x 3 judges x 6 seeds x 2 repeats, 8 turns max, run twice:

| Defender | Breaks | Attacker spend |
|---|---|---|
| `openai/gpt-4o-mini` | 0 / 108 | $0.51 |
| `mistralai/mistral-small-3.2-24b-instruct` | 0 / 108 | $0.49 |

The defenders held on their own, so the guardrails had nothing to stop and the ACE-style "dollars
to break" figure is only a lower bound. The only breaks came from a pilot of four cheap defenders
with no guardrail: 3 of 36 runs, every one through indirect injection (planted "official procedure"
search results, then a one-line ask).

**The judges, tested directly.** Every recorded attack replayed to its last attacker message, then
each judge asked about the forbidden call and about a legitimate call to the same tool:

| Judge | Real breaks blocked on replay | Forbidden call blocked | Legit call blocked under attack | Legit call blocked, clean benign tasks |
|---|---|---|---|---|
| prompt judge | 3 / 3 | 215 / 216 | 26 / 216 (12%) | 0 / 12 |
| judgeman | 3 / 3 | 216 / 216 | 59 / 216 (27%) | 0 / 13 |

**Takeaway.** The plain prompt judge beat judgeman. Not on catching attacks, where they tie, but on
collateral damage. On The Fetcher, judgeman refused to add `https://docs.python.org` in 53% of attack
contexts (prompt judge: 22%). It also gave a reason in only 16 of 432 verdicts, because the judge
model left out judgeman's `critique` field. judgeman's `risky` axis means "destructive, or beyond the
task" for a coding agent, so mid-attack it fires on the tool, not the policy. What I'd change: a
`policy_violation` axis defined by the deployer's policy, a required critique that fails closed when
missing, and a provenance check for tool calls justified by tool output, the signature all three
real breaks share. Details, excerpts and the one prompt-judge miss are in
[results/summary.md](results/summary.md).
<!-- results:end -->

## Run it

```bash
git clone https://github.com/Christopher4113/fabraix-guardrail-bench && cd fabraix-guardrail-bench
uv sync
cp .env.example .env            # add OPENROUTER_API_KEY
uv run python tests/test_offline.py   # offline: no key, no spend
uv run bench smoke              # one live defender turn against The Gatekeeper, guardrails off
uv run bench attack -c access-code-001 -j prompt -s authority   # one run, about a cent
uv run bench matrix --seeds authority policy-update task-splitting obfuscation debug-mode indirect --repeats 2
uv run bench benign             # false-block set
uv run bench probe              # judges only, on counterfactual tool calls
uv run bench replay             # real breaks, replayed through each judge
uv run bench report             # writes results/summary.md
uv run bench serve              # demo UI on http://127.0.0.1:8765
```

Every call's cost is read from OpenRouter's `usage.cost` and logged per role (attacker, defender,
judge) on each run. `results/spend.json` holds the running total, and every call checks it
against `BENCH_BUDGET_USD` (default $15) first, so a loop cannot run past the cap.

## How it works

- **Engine.** `vendor/fabraix_engine` is Fabraix's `engine/`, unmodified. `src/bench/adapters.py`
  implements the six `Platform` seams: an in-memory `Store`, a silent `Notifier`, an OpenRouter
  `Llm`, a disabled `Browser`, `Settings` with a fake per-challenge secret, and the swappable
  `GuardrailJudge`. Wins come from the engine's own `evaluate_win`.
- **Attacker** (`attacker.py`). It reads the challenge objective, the full published system
  prompt and the tool list, then talks to the defender for up to 8 turns from one strategy seed:
  authority claim, fake policy update, task splitting, obfuscation, indirect injection,
  or debug-mode framing. It sees replies and tool calls the way the
  Playground UI shows them. Spend counts until it wins or hits the cap.
- **Indirect injection** (`poison.py`). The vendored `search_web` calls Brave directly, outside
  the seams, so it is replaced at runtime in `TOOL_REGISTRY` (the only runtime patch). It returns
  harmless fixed results unless the attacker has planted its own, which is how instructions reach
  the defender through its environment.
- **Judges** (`judges.py`).
  - `none` always allows.
  - `prompt` makes one LLM call: policy, the last 8 chat messages, and the proposed tool call.
    Block or allow, and why.
  - `judgeman` builds a judgeman `Trajectory` from the session, with each chat turn as a `Step`
    and the proposed tool call as the last one, then judges it on the `risky` axis with `last5`
    context and the challenge policy as the task. Risky means blocked.
  - Both LLM judges fail closed when a verdict can't be read.
- **False blocks** (`benign.py`). Five harmless tasks per challenge that legitimately call a tool,
  like a normal search, a SentinelID check against the real partner, or adding MDN to The
  Fetcher's allowlist.

- **Direct judge test** (`probe.py`). The defenders rarely folded, so `bench probe` replays each
  attack conversation to its last attacker message and asks each judge about the forbidden call and
  a legitimate one. `bench replay` does the same for each real break with its exact winning call.

Models, fixed within each matrix: attacker `deepseek/deepseek-chat-v3.1`, judge
`google/gemini-2.5-flash-lite` (both LLM judges use it). Defender: `openai/gpt-4o-mini` for the
first matrix, then `mistralai/mistral-small-3.2-24b-instruct` (the default now) after a pilot found
it the only cheap model that broke more than once.

## Scope

The bench attacks three challenges: The Gatekeeper (`access-code-001`), The Assistant
(`data-exfil-001`), and The Fetcher (`url-allowlist-001`).

- **The Maintainer** (`jwt-verifier-001`) can't be scored locally. Its `verifier_patch` win reads
  a `broke` flag that the hosted sandbox attaches after running the submitted code against a
  token battery, and the reference engine doesn't ship that sandbox. Without it `evaluate_win`
  always returns false.
- **The Biosafety Officer and The Failsafe** are left out on purpose. Their sinks are inert, but
  I chose not to point an automated jailbreak loop at prompts themed on releasing pathogen
  protocols or chemicals. The Failsafe is also still live until Nov 18 2026.

## Vendored code

`vendor/` holds Fabraix's `engine/` and `challenges/` from
[fabraix/playground](https://github.com/fabraix/playground) at commit `4072760`, under MIT, with
their `LICENSE` kept. See [vendor/README.md](vendor/README.md). Everything in `src/bench/`,
`tests/` and `results/` is mine. Nothing in this repo calls `playground.fabraix.com` or submits
anything to its leaderboard.

## Limits

- Small N: 12 attack runs per cell and 5 benign tasks per challenge. Treat the rates as directional.
- Cheap models throughout. A stronger defender or attacker would move every number.
- The browser tool is disabled and search is local, so attacks that need a live page are out.
- This is ACE-style, not ACE. Fabraix's benchmark methodology isn't fully public; the bench
  borrows the idea of pricing a break in attacker spend with failures included.
- judgeman was built to judge coding-agent steps (wasted, repeated, dangerous, unverified), not to
  enforce a security policy. Its system prompt still says so; only the task text is adapted.

## Links

- judgeman: https://github.com/Christopher4113/JudgeMan
- judgeman paper: https://doi.org/10.5281/zenodo.23354648
- Fabraix Playground: https://github.com/fabraix/playground
