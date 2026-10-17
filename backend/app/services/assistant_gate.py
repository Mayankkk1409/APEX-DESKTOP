"""Decide whether a question may reach the model.

The model is not the entitlement check. Screen text is never part of this decision,
and it is not forwarded.
"""

from __future__ import annotations

import re

from app.services.assistant_plans import PLAN_BY_ID

QuestionKind = str  # "basic" | "screen" | "complex"
Decision = str  # "allow" | "upgrade" | "boundary"

_SCREEN = re.compile(
    r"("
    r"\b(on|at) (my |the |this )?(screen|page|desk)\b"
    r"|this (screen|page|chart|graph|desk|view|panel|number|figure|popup|dialog|card)\b"
    r"|\b(the|my) (current )?(screen|chart|graph)\b"
    r"|what am i looking at"
    r"|explain (this|the chart|the graph|the screen|the page|my )\b"
    r"|\bmy (portfolio|position|positions|order|orders|holding|holdings|p&l|pnl|scan|score)\b"
    r")",
    re.IGNORECASE,
)

_COMPLEX = re.compile(
    r"("
    r"\bshould i\b"
    r"|\brecommend"
    r"|\bprice target\b"
    r"|\bbuy or sell\b"
    r"|\btrade idea\b"
    r"|\b(analyze|analyse|analysis|research)\b"
    r"|\bbest (trade|strategy|option|setup)\b"
    r"|\b(outlook|forecast)\b"
    r"|\bgoing to\b"
    r"|\bworth buying\b"
    r")",
    re.IGNORECASE,
)

_GREETING = re.compile(
    r"^(hi|hello|hey|thanks|thank you|good morning|good afternoon)[!.?\s]*$",
    re.IGNORECASE,
)

_NAVIGATION = re.compile(
    r"("
    r"where (is|are|do i|can i)"
    r"|how do i (find|open|get to|go to|see|use)"
    r")"
    r".{0,60}(portfolio|settings|scan|deep scan|chart|desk|sign in|login|order history|positions)",
    re.IGNORECASE,
)

_DEFINITION = re.compile(
    r"^(what is|what are|what's|whats|what does|define|meaning of|explain)\b",
    re.IGNORECASE,
)


def classify_question(message: str) -> QuestionKind:
    text = " ".join(message.split())
    if _SCREEN.search(text):
        return "screen"
    if _COMPLEX.search(text):
        return "complex"
    if _GREETING.fullmatch(text) or _NAVIGATION.search(text):
        return "basic"
    if _DEFINITION.match(text) and len(text) <= 220:
        return "basic"
    return "complex"


def decide_access(plan_id: str, kind: QuestionKind) -> Decision:
    """Free accounts get glossary and navigation only.

    Paid plans are listed, but the screen-analysis and research boundary was not
    defined. Those questions do not reach the model, and they do not ask a paid
    account to upgrade.
    """
    if plan_id not in PLAN_BY_ID:
        plan_id = "free"
    if kind == "basic":
        return "allow"
    if plan_id == "free":
        return "upgrade"
    return "boundary"
