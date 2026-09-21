"""The swappable policy document.

Policy is data, not code: `docs/policy.md` is authored in another lane, carries its own
provenance, and drops in without a code change. This module reads it, extracts the rule
IDs agents must cite, and fails loudly when the file is missing — a run without policy is
not a run this system is willing to make.

Rule definition convention accepted by the loader (a line *begins* a rule when the rule
ID is its first token, after any markdown decoration):

    ### RD-1 — Route deviation threshold      heading style
    **RD-1** Route deviation threshold        bold style
    | RD-1 | Route deviation threshold | ...  table-row style

A rule ID that appears mid-sentence is a cross-reference, not a definition, and is
ignored. If an ID is defined twice, the first definition wins.

The loader exposes rule IDs and rule text. Evaluating the machine-checkable preconditions
against an Evidence Pack is a later capability; nothing here interprets policy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

#: Rule IDs look like RD-1, NS-2, GEN-1 — 2-5 capitals, a hyphen, a number.
RULE_ID_PATTERN = re.compile(r"\b([A-Z]{2,5}-\d{1,3})\b")

#: A line defines a rule only when its first token is the rule ID.
_DEFINITION_PATTERN = re.compile(r"^[\s#*|>\-]*([A-Z]{2,5}-\d{1,3})\b")


class PolicyError(RuntimeError):
    """The policy document is missing, unreadable, or has no usable rules."""


@dataclass(frozen=True)
class PolicyRule:
    """One rule, with the text that defines it."""

    rule_id: str
    text: str
    line_number: int


@dataclass(frozen=True)
class PolicySet:
    """The loaded policy document."""

    source_path: Path
    text: str
    rules: List[PolicyRule]

    def rule_ids(self) -> List[str]:
        return [rule.rule_id for rule in self.rules]

    def has_rule(self, rule_id: str) -> bool:
        return any(rule.rule_id == rule_id for rule in self.rules)

    def rule_text(self, rule_id: str) -> str:
        for rule in self.rules:
            if rule.rule_id == rule_id:
                return rule.text
        raise KeyError("no rule %r in %s" % (rule_id, self.source_path))

    def unknown_rule_ids(self, cited: Iterable[str]) -> List[str]:
        """Which of the cited IDs are not in the document — i.e. invented by a model."""
        known = set(self.rule_ids())
        return [rule_id for rule_id in cited if rule_id not in known]


def extract_rules(text: str) -> List[PolicyRule]:
    """Split a policy document into rule blocks, in document order."""
    rules: List[PolicyRule] = []
    seen: Dict[str, PolicyRule] = {}
    current: Optional[PolicyRule] = None
    buffer: List[str] = []

    def flush() -> None:
        if current is not None and current.rule_id not in seen:
            block = PolicyRule(current.rule_id, "\n".join(buffer).strip(), current.line_number)
            seen[current.rule_id] = block
            rules.append(block)

    for line_number, line in enumerate(text.splitlines(), start=1):
        match = _DEFINITION_PATTERN.match(line)
        if match:
            flush()
            current = PolicyRule(match.group(1), "", line_number)
            buffer = [line]
            continue
        if current is not None:
            buffer.append(line)

    flush()
    return rules


def load_policy(path: Path) -> PolicySet:
    """Load and validate the policy document. Raises PolicyError if it cannot be used."""
    policy_path = Path(path)
    if not policy_path.exists():
        raise PolicyError(
            "policy document not found at %s. The policy set is a required input: it is "
            "authored separately and must land at that path before the pipeline can run. "
            "Tests use the minimal fixture in tests/fixtures/ instead." % policy_path
        )
    if not policy_path.is_file():
        raise PolicyError("policy path is not a file: %s" % policy_path)

    text = policy_path.read_text(encoding="utf-8")
    if not text.strip():
        raise PolicyError("policy document is empty: %s" % policy_path)

    rules = extract_rules(text)
    if not rules:
        raise PolicyError(
            "no rules found in %s. Rules must be numbered IDs whose first token on a line "
            "is the ID, e.g. '### RD-1 — Route deviation threshold'." % policy_path
        )
    return PolicySet(source_path=policy_path, text=text, rules=rules)
