"""Load prompt templates from YAML files in the templates/ directory."""

from pathlib import Path
from typing import Any

import yaml
from langchain_core.prompts import ChatPromptTemplate

_TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates"


def load_prompt(name: str, version: str = "v1") -> ChatPromptTemplate:
    """Load a named prompt template.

    Args:
        name: Template name (e.g. "recommend").
        version: Version string (e.g. "v1").

    Returns:
        A ChatPromptTemplate ready for use in an LCEL chain.
    """
    path = _TEMPLATES_DIR / f"{name}_{version}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Prompt template not found: {path}")

    with path.open() as f:
        data: dict[str, Any] = yaml.safe_load(f)

    messages = []
    for msg in data["messages"]:
        role = msg["role"]
        content = msg["content"]
        messages.append((role, content))

    return ChatPromptTemplate.from_messages(messages)
