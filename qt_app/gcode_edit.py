from __future__ import annotations

import re


_LINE_NUMBER = re.compile(r"^(\s*)N\d+\s*", re.IGNORECASE)


def remove_line_numbers(content: str) -> str:
    """Remove a leading CNC block number without touching N inside comments/code."""
    return "\n".join(_LINE_NUMBER.sub(r"\1", line) for line in content.split("\n"))


def add_line_numbers(content: str, start: int = 10, step: int = 10) -> str:
    """Number non-empty program blocks; `%` delimiters remain unnumbered."""
    clean = remove_line_numbers(content)
    number = start
    output: list[str] = []
    for line in clean.split("\n"):
        stripped = line.strip()
        if not stripped or stripped == "%":
            output.append(line)
            continue
        leading = line[: len(line) - len(line.lstrip())]
        output.append(f"{leading}N{number} {line.lstrip()}")
        number += step
    return "\n".join(output)


def replace_all(content: str, search: str, replacement: str) -> str:
    return content.replace(search, replacement) if search else content
