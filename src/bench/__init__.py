"""Guardrail bench over the vendored Fabraix Playground engine.

The engine lives in vendor/fabraix_engine and is imported as `fabraix_engine`, unmodified.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = Path(os.environ.get("BENCH_RESULTS", ROOT / "results"))
sys.path.insert(0, str(ROOT / "vendor"))

# The bench attacks only these. biosafety-001 and chemsafety-001 are left out on purpose
# (see README, "Scope"). jwt-verifier-001 cannot be scored by the reference engine: its
# verifier_patch win reads a `broke` flag that only the hosted sandbox sets.
CHALLENGES = ("access-code-001", "data-exfil-001", "url-allowlist-001")
