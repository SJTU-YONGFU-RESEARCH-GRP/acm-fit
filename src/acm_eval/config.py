"""Load and validate the evaluation-suite policy file."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


SUPPORTED_ANALYSES = ("dc", "ac", "noise", "transient", "temp")
SUPPORTED_SIMULATORS = ("ngspice", "spectre", "hspice")


@dataclass(frozen=True)
class PdkEvalConfig:
    """PDK settings for golden BSIM capture (ngspice models only)."""

    name: str
    vdd: float
    width: str
    length: str
    width_m: float
    length_m: float
    sections: Mapping[str, str]
    ref_devices: Mapping[str, str]


@dataclass(frozen=True)
class SuiteConfig:
    """Top-level evaluation suite configuration."""

    suite_version: int
    default_analyses: tuple[str, ...]
    default_simulators: tuple[str, ...]
    analysis_defaults: Mapping[str, Mapping[str, Any]]
    pdks: Mapping[str, PdkEvalConfig]


def _expand_env(template: str, env: Mapping[str, str], repo_root: Path) -> str:
    """Expand ``${VAR}`` placeholders from entry env and ``os.environ``."""
    placeholders = set(re.findall(r"\$\{([^}]+)\}", template))
    merged: dict[str, str] = dict(env)
    for key in placeholders:
        if key in os.environ and os.environ[key]:
            merged[key] = os.environ[key]
    out = template
    for key in placeholders:
        if key not in merged or not merged[key]:
            raise ValueError(
                f"unresolved placeholder ${{{key}}} in {template!r}; "
                f"set {key} in config/pdk_env.local.json or export it"
            )
        value = merged[key]
        path_value = value
        if value and not Path(value).is_absolute() and "${" not in value:
            path_value = str((repo_root / value).resolve())
        out = out.replace(f"${{{key}}}", path_value)
    return out


def load_suite_config(path: Path, repo_root: Path) -> SuiteConfig:
    """Load suite policy JSON and validate required keys."""
    if not path.is_file():
        raise FileNotFoundError(f"missing eval suite config: {path}")
    raw = json.loads(path.read_text())
    analyses = tuple(raw.get("default_analyses", []))
    sims = tuple(raw.get("default_simulators", []))
    unknown_a = [a for a in analyses if a not in SUPPORTED_ANALYSES]
    unknown_s = [s for s in sims if s not in SUPPORTED_SIMULATORS]
    if unknown_a:
        raise ValueError(f"unsupported analyses in config: {unknown_a}")
    if unknown_s:
        raise ValueError(f"unsupported simulators in config: {unknown_s}")

    pdks: dict[str, PdkEvalConfig] = {}
    for name, entry in raw["pdks"].items():
        env = {k: str(v) for k, v in entry.get("env", {}).items()}
        for key in list(env):
            if key in os.environ and os.environ[key]:
                env[key] = os.environ[key]
        ngspice_section = _expand_env(entry["ngspice_section"], env, repo_root)
        ref_raw = entry["ref_device"]
        if isinstance(ref_raw, str):
            ref_devices = {"ngspice": ref_raw}
        else:
            if "ngspice" not in ref_raw:
                raise ValueError(f"PDK {name!r}: ref_device missing ngspice entry")
            ref_devices = {"ngspice": str(ref_raw["ngspice"])}
        pdks[name] = PdkEvalConfig(
            name=name,
            vdd=float(entry["vdd"]),
            width=str(entry["width"]),
            length=str(entry["length"]),
            width_m=float(entry["width_m"]),
            length_m=float(entry["length_m"]),
            sections={"ngspice": ngspice_section},
            ref_devices=ref_devices,
        )

    return SuiteConfig(
        suite_version=int(raw["suite_version"]),
        default_analyses=analyses,
        default_simulators=sims,
        analysis_defaults=raw["analysis_defaults"],
        pdks=pdks,
    )


__all__ = [
    "SUPPORTED_ANALYSES",
    "SUPPORTED_SIMULATORS",
    "PdkEvalConfig",
    "SuiteConfig",
    "load_suite_config",
]
