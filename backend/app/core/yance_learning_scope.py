"""Pure scope filter for Yance-promoted rules stored in Agent.instructions.

Persistence remains Agent.instructions.  This module only strips Yance scope
markers and excludes contact rules that do not belong to the current customer.
"""
from __future__ import annotations

import re
from collections.abc import Iterable

_SCOPE = re.compile(
    r"^\[\[YANCE_SCOPE:(global|contact:([^\]]+))\]\]\s*(.*)$",
    flags=re.DOTALL,
)


def effective_agent_instructions(
    instructions: Iterable[str] | None,
    customer_id: str | None,
) -> list[str]:
    effective: list[str] = []
    current_customer = str(customer_id) if customer_id is not None else None
    for raw in instructions or []:
        text = str(raw)
        match = _SCOPE.match(text)
        if not match:
            effective.append(text)
            continue

        scope, scoped_customer, rule = match.groups()
        rule = rule.strip()
        if not rule:
            continue
        if scope == "global":
            effective.append(rule)
        elif current_customer is not None and scoped_customer == current_customer:
            effective.append(rule)
    return effective
