"""Runtime configuration: settings from app/config.json, secrets from the environment.

Split rule (keeps the public repo clean):
  * settings   -> app/config.json   (committed; threshold, provider, paths, dataset pack)
  * secrets    -> .env / environment (never committed; API keys only)

The dataset pack names which corpus under data/packs/ the CLI reads disputes from;
`resolve_pack_dir` turns the name into a path and refuses an unknown one.

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

#: Where the swappable dispute corpora live, and which one runs unless config says
#: otherwise. A pack is a directory holding disputes/, ground-truth.json and pack.json;
#: swapping one in is a directory copy, never a code change.
DATASET_PACKS_DIR = REPO_ROOT / "data" / "packs"
DEFAULT_DATASET_PACK = "organiser-style-v1"


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
    autonomous_cap_sgd: float
    llm: LLMSettings
    policy_path: Path
    out_dir: Path
    source_path: Path
    #: The dataset pack to read disputes from: its name, and its resolved directory.
    dataset_pack: str
    dataset_pack_dir: Path


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


def _pack_name(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError("dataset_pack must be a non-empty pack name, got %r" % (value,))
    return value.strip()


def resolve_pack_dir(name: str) -> Path:
    """Resolve a dataset pack name to its directory under data/packs/.

    Raises ConfigError for a name that is not a pack, listing what is available: a run
    against a pack that does not exist must fail before it reads anything, not part-way
    through with a missing dispute file.
    """
    pack_name = _pack_name(name)
    path = (DATASET_PACKS_DIR / pack_name).resolve()
    if not (path / "disputes").is_dir():
        available = ", ".join(sorted(p.name for p in DATASET_PACKS_DIR.glob("*") if (p / "disputes").is_dir()))
        raise ConfigError(
            "unknown dataset pack %r: %s has no disputes/ directory. Available packs: %s"
            % (pack_name, path, available or "(none)")
        )
    return path


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

    # ESC-4's autonomous decision cap. A remedy above this is prepared but never issued
    # without a human. Defaults to the policy's stated SGD 50.00 when the key is absent,
    # so an older config file cannot silently disable the gate.
    cap = data.get("autonomous_cap_sgd", 50.00)
    if isinstance(cap, bool) or not isinstance(cap, (int, float)):
        raise ConfigError("%s: autonomous_cap_sgd must be a number, got %r" % (where, cap))
    cap = float(cap)
    if cap <= 0.0:
        raise ConfigError(
            "%s: autonomous_cap_sgd must be greater than 0, got %r. A cap of zero or less "
            "would withhold every ruling that moves money." % (where, cap)
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

    # Which corpus to run on. Defaulted rather than required, so a config file written
    # before the packs existed still loads and still names a real pack.
    pack_name = _pack_name(data.get("dataset_pack", DEFAULT_DATASET_PACK))
    pack_dir = resolve_pack_dir(pack_name)

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
        autonomous_cap_sgd=cap,
        llm=llm,
        policy_path=policy_path,
        out_dir=out_dir,
        source_path=config_path.resolve(),
        dataset_pack=pack_name,
        dataset_pack_dir=pack_dir,
    )
