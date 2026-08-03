"""Publish concise pytest JUnit failures as GitHub Check annotations."""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def _escape(value: str) -> str:
    """Escape GitHub workflow command data."""
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def annotations(report: Path) -> list[str]:
    root = ET.parse(report).getroot()
    emitted = []
    for case in root.iter("testcase"):
        problem = next(
            (child for child in case if child.tag in {"failure", "error"}),
            None,
        )
        if problem is None:
            continue
        test_id = f"{case.attrib.get('classname', 'pytest')}.{case.attrib.get('name', 'test')}"
        details = problem.attrib.get("message") or problem.text or "pytest failed"
        summary = next((line.strip() for line in details.splitlines() if line.strip()), details)
        emitted.append(
            f"::error file=tests,title={_escape(test_id)}::{_escape(summary)}"
        )
    return emitted


def main() -> int:
    report = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".pytest-results.xml")
    if not report.is_file():
        print("::error file=.github,title=pytest::JUnit report was not created")
        return 1
    for annotation in annotations(report):
        print(annotation)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
