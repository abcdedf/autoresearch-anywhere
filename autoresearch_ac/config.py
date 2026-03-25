"""Read and write config.yaml and research.yaml."""

from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path("config.yaml")
DEFAULT_RESEARCH_PATH = Path("research.yaml")


def load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML file and return its contents as a dict."""
    if not path.exists():
        return {}
    with open(path) as f:
        return yaml.safe_load(f) or {}


def save_yaml(path: Path, data: dict[str, Any]) -> None:
    """Write a dict to a YAML file."""
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """Load platform config."""
    return load_yaml(path)


def save_config(data: dict[str, Any], path: Path = DEFAULT_CONFIG_PATH) -> None:
    """Save platform config."""
    save_yaml(path, data)


def load_research(path: Path = DEFAULT_RESEARCH_PATH) -> dict[str, Any]:
    """Load research config."""
    return load_yaml(path)
