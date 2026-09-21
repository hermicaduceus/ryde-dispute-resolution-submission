"""Runtime configuration: settings from app/config.json, secrets from the environment.

Split rule (keeps the public repo clean):
  * settings   -> app/config.json   (committed; threshold, provider, paths)
  * secrets    -> .env / environment (never committed; API keys only)

The confidence threshold is read from config and passed explicitly into the pipeline.
It is never hard-coded in agent logic, so the demo can change it live by editing the
config file and re-running.

Standard library only: json + a minimal .env reader (python-dotenv is not a dependency
of this project and the .env format we need is three lines long).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "app" / "config.json"
DEFAULT_ENV_PATH = REPO_ROOT / ".env"


class ConfigError(RuntimeError):
    """Configuration is missing, unreadable or out of range."""


# --------------------------------------------------------------------------- .env


def load_env_file(path: Optional[Path] = None) -> Dict[str, str]:
    """Read a .env file into a dict. Returns {} when the file does not exist.

    Accepts `KEY=value`, optional `export ` prefix, `#` comments and single or double
    quoted values. Deliberately minimal — enough for the two variables this project uses.
    """
    env_path = Path(path) if path is not None else DEFAULT_ENV_PATH
    if not env_path.exists():
        return {}

    values: Dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def read_secret(name: str, env_path: Optional[Path] = None) -> Optional[str]:
    """Look up a secret: real environment first, then the .env file. None if unset.

    The environment wins so a shell export can override a stale local file.
    """
    from_environ = os.environ.get(name)
    if from_environ:
        return from_environ
    value = load_env_file(env_path).get(name)
    return value or None


# --------------------------------------------------------------------------- config


@dataclass(frozen=True)
class LLMSettings:
    """Which provider to call and how. The API key is not here — it is a secret."""

    provider: str
    endpoint: str
    model: str
    temperature: float
    max_tokens: int
    timeout_seconds: int


@dataclass(frozen=True)
class Config:
    """Everything the pipeline needs to run one dispute."""

    confidence_threshold: float
    llm: LLMSettings
    policy_path: Path
    out_dir: Path
    source_path: Path


def _require_mapping(data: Dict[str, Any], key: str, where: str) -> Dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise ConfigError("%s: '%s' must be an object, got %r" % (where, key, value))
    return value


def _resolve_path(value: Any, key: str, where: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError("%s: paths.%s must be a non-empty string, got %r" % (where, key, value))
    path = Path(value.strip())
    return path if path.is_absolute() else (REPO_ROOT / path).resolve()


def load_config(path: Optional[Path] = None) -> Config:
    """Load and validate app/config.json. Raises ConfigError with a readable message."""
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    if not config_path.exists():
        raise ConfigError("config file not found: %s" % config_path)
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError("config file is not valid JSON (%s): %s" % (config_path, exc)) from exc
    if not isinstance(data, dict):
        raise ConfigError("config file must contain a JSON object: %s" % config_path)

    where = str(config_path)

    threshold = data.get("confidence_threshold")
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise ConfigError("%s: confidence_threshold must be a number, got %r" % (where, threshold))
    threshold = float(threshold)
    if not 0.0 <= threshold <= 1.0:
        raise ConfigError(
            "%s: confidence_threshold must be between 0 and 1, got %r" % (where, threshold)
        )

    llm_raw = _require_mapping(data, "llm", where)
    provider = llm_raw.get("provider")
    if not isinstance(provider, str) or not provider.strip():
        raise ConfigError("%s: llm.provider must be a non-empty string" % where)

    temperature = llm_raw.get("temperature", 0.0)
    if isinstance(temperature, bool) or not isinstance(temperature, (int, float)):
        raise ConfigError("%s: llm.temperature must be a number" % where)

    max_tokens = llm_raw.get("max_tokens", 1500)
    if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens <= 0:
        raise ConfigError("%s: llm.max_tokens must be a positive integer" % where)

    timeout = llm_raw.get("timeout_seconds", 60)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
        raise ConfigError("%s: llm.timeout_seconds must be a positive number" % where)

    paths_raw = _require_mapping(data, "paths", where)
    policy_path = _resolve_path(paths_raw.get("policy"), "policy", where)
    out_dir = _resolve_path(paths_raw.get("out_dir"), "out_dir", where)

    llm = LLMSettings(
        provider=provider.strip(),
        endpoint=str(llm_raw.get("endpoint", "") or ""),
        model=str(llm_raw.get("model", "") or ""),
        temperature=float(temperature),
        max_tokens=int(max_tokens),
        timeout_seconds=int(timeout),
    )

    return Config(
        confidence_threshold=threshold,
        llm=llm,
        policy_path=policy_path,
        out_dir=out_dir,
        source_path=config_path.resolve(),
    )
