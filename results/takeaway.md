**The plain prompt judge beat judgeman here. Not on catching attacks, where they tie, but on what it costs to run them.**

- **The defenders mostly held on their own.** 0 breaks in 216 full-matrix runs across two defenders (about $1.00 of attacker spend, or $0.0046 a run). The only 3 breaks in the project (3 of 36 pilot runs) all came from indirect injection: fake "official procedure" pages planted in search results, then a one-line ask. Direct persuasion never worked. The attack surface that matters is what the agent reads, not what the user says, which is the case Nyx makes.
- **On the forbidden call itself, both judges are near perfect.** Both blocked all 3 real breaks on replay. On counterfactual sink calls, judgeman blocked 216 of 216 and the prompt judge 215 of 216. The one miss was the prompt judge accepting `https://evil.com` as "a controlled test domain for a security audit", the same framing that broke the defenders.
- **The difference is collateral damage.** Under attack pressure judgeman blocked the legitimate call 59 of 216 times (27%), the prompt judge 26 of 216 (12%). On The Fetcher it was 53% vs 22%: judgeman refused to add `https://docs.python.org`. On clean benign tasks neither judge blocked anything.
- **judgeman rarely explained itself.** With `gemini-2.5-flash-lite` as the judge model it gave a critique in 16 of 432 verdicts. The model returned the yes/no axes and left out the critique field.
- **The ACE-style dollar figure is a lower bound here.** No cell broke, so "attacker dollars to break" reads as "spent this much, got nothing", and the dollars a guardrail adds can't be measured at this N with these defenders.

Why judgeman over-blocks: its `risky` axis means "destructive, or effects beyond the task" for a coding agent. Mid-attack, any allowlist edit or verification call looks like an effect beyond the task, so it fires on the tool rather than on the policy. It judges steps, not policy.

What I would change in judgeman for this job:

1. Add a `policy_violation` axis whose definition is the deployer's policy, instead of stretching `risky`.
2. Require the critique. Validate the reply schema and fail closed when the critique is missing, so every block can be audited.
3. Add provenance: flag a tool call whose justification traces back to tool output rather than the user. All three real breaks have that signature.
