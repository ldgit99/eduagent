"""Eval-guided self-improvement (plan v2 §16).

Not a self-evolving agent. A **deterministic workflow** with four safeguards, each
taken from something that has been shown to work:

* The signal is *score plus textual failure evidence*, not a scalar — GEPA's
  reflective contract. A diagnosis quotes the turn that failed.
* Edits are layered, and the autonomy dial says which layers may apply without a
  human (Claude Code's permission modes). Design principles are never auto-edited:
  those are the student's pedagogical decisions, and quietly rewriting them would
  defeat the entire point of the harness.
* Adoption is gated: a change must clear a minimum improvement **and** break no
  previously passing hard constraint, measured on scenarios held out from the
  diagnosis (prompt-CI practice, GEPA's held-out valset).
* Rollback is a pointer move over versioned snapshots.
"""

from edu_agent.optimizer.diagnose import Diagnosis, EditLayer, diagnose
from edu_agent.optimizer.gate import GateVerdict, evaluate_change
from edu_agent.optimizer.loop import ImproveOutcome, ImproveRound, run_improve
from edu_agent.optimizer.patch import Patch, apply_patches, revert_to
from edu_agent.optimizer.proposals import Proposal, propose

__all__ = [
    "Diagnosis",
    "EditLayer",
    "GateVerdict",
    "ImproveOutcome",
    "ImproveRound",
    "Patch",
    "Proposal",
    "apply_patches",
    "diagnose",
    "evaluate_change",
    "propose",
    "revert_to",
    "run_improve",
]
