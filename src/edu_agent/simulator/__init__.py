"""Synthetic learners (plan v2 §13)."""

from edu_agent.simulator.loop import SimulationResult, run_simulation
from edu_agent.simulator.personas import default_personas, load_personas
from edu_agent.simulator.state import SimulatedStudent, StudentState, StudentTurn

__all__ = [
    "SimulatedStudent",
    "SimulationResult",
    "StudentState",
    "StudentTurn",
    "default_personas",
    "load_personas",
    "run_simulation",
]
