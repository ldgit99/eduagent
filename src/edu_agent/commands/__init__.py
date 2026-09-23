"""What each CLI command actually does, separated from how it is invoked.

``cli.py`` parses arguments and prints results; these modules do the work, and
can be driven directly by a test or by another program.
"""

from edu_agent.commands import (
    calibrate,
    chat,
    context,
    diagnose,
    evaluate,
    export,
    improve,
    review,
)

__all__ = [
    "calibrate",
    "chat",
    "context",
    "diagnose",
    "evaluate",
    "export",
    "improve",
    "review",
]
