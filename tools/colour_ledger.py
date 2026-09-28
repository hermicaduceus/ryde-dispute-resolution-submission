"""Colour ledger: every colour-bearing declaration in the two stylesheets, in source order.

Why this exists (glm-5.3 review of sessions twelve and thirteen, 2026-09-29): the
selector-list pins in tests/test_console_rebrand.py only see the rules they name. A new
rule appended at the end of a file, a status rule nobody listed, or a swap between two
accent tokens all changed real rendered colours while the suite stayed green (15 of 22
mutations survived). The ledger closes that class: ANY change to a colour declaration,
anywhere, turns tests/test_session_sixteen.py red until the ledger is re-baselined on
purpose.

Duplicates are kept and order is kept, because the cascade depends on both.

Usage:
    python3 tools/colour_ledger.py            # print the ledger as JSON
    python3 tools/colour_ledger.py --write    # re-baseline tests/fixtures/colour_ledger.json

Re-baseline only after a colour change the operator has approved.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Dict, List

REPO = Path(__file__).resolve().parent.parent
SHEETS = ["ui/styles.css", "ui/party/party.css"]
FIXTURE = REPO / "tests" / "fixtures" / "colour_ledger.json"

_COLOUR_PROP = re.compile(
    r"^(--[\w-]+|color|background(-color|-image)?|border(-(top|right|bottom|left))?(-color)?"
    r"|outline(-color)?|box-shadow|text-decoration(-color)?|fill|stroke|caret-color|accent-color)$"
)
_COLOUR_VALUE = re.compile(r"var\(|#|rgb|hsl|transparent|currentcolor|\b(white|black)\b")


def ledger_for(css: str) -> List[List[str]]:
    """[selector list, property, value] for every colour declaration, source order."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S).lower()
    rows: List[List[str]] = []
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        selector = ", ".join(" ".join(s.split()) for s in match.group(1).split(","))
        for prop, value in re.findall(r"([\w-]+)\s*:\s*([^;]+);?", match.group(2)):
            prop = prop.strip()
            value = " ".join(value.split())
            if _COLOUR_PROP.match(prop) and (prop.startswith("--") or _COLOUR_VALUE.search(value)):
                rows.append([selector, prop, value])
    return rows


def build(repo: Path = REPO) -> Dict[str, List[List[str]]]:
    return {sheet: ledger_for((repo / sheet).read_text(encoding="utf-8")) for sheet in SHEETS}


if __name__ == "__main__":
    data = build()
    text = json.dumps(data, indent=1) + "\n"
    if "--write" in sys.argv[1:]:
        FIXTURE.write_text(text, encoding="utf-8")
        print("wrote %s (%s)" % (FIXTURE, ", ".join("%s: %d" % (k, len(v)) for k, v in data.items())))
    else:
        sys.stdout.write(text)
