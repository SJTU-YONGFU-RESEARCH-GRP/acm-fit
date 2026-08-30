"""Content-hash cache so unchanged models skip re-simulation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class JobFingerprint:
    """Stable fingerprint inputs for one evaluation job."""

    suite_version: int
    pdk: str
    model: str
    simulator: str
    analysis: str
    va_sha256: str
    osdi_sha256: str
    card: Mapping[str, float]
    analysis_params: Mapping[str, object]
    pdk_section: str
    ref_device: str


def file_sha256(path: Path) -> str:
    """Return hex SHA-256 of a file.

    Args:
        path: File to hash.

    Returns:
        Hex digest string.

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    if not path.is_file():
        raise FileNotFoundError(f"missing file for fingerprint: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint_digest(fp: JobFingerprint) -> str:
    """Serialize fingerprint fields to a stable SHA-256 digest."""
    payload = {
        "suite_version": fp.suite_version,
        "pdk": fp.pdk,
        "model": fp.model,
        "simulator": fp.simulator,
        "analysis": fp.analysis,
        "va_sha256": fp.va_sha256,
        "osdi_sha256": fp.osdi_sha256,
        "card": dict(sorted(fp.card.items())),
        "analysis_params": fp.analysis_params,
        "pdk_section": fp.pdk_section,
        "ref_device": fp.ref_device,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


def cache_paths(job_dir: Path) -> tuple[Path, Path]:
    """Return ``(fingerprint.json, success.marker)`` paths for a job dir."""
    return job_dir / "fingerprint.json", job_dir / "SUCCESS"


def should_skip(job_dir: Path, digest: str) -> bool:
    """Return True when a prior successful run matches ``digest``."""
    fp_path, ok_path = cache_paths(job_dir)
    if not fp_path.is_file() or not ok_path.is_file():
        return False
    stored = json.loads(fp_path.read_text())
    return stored.get("digest") == digest


def write_cache(job_dir: Path, digest: str, fingerprint: JobFingerprint) -> None:
    """Persist fingerprint metadata and success marker."""
    fp_path, ok_path = cache_paths(job_dir)
    payload = {
        "digest": digest,
        "pdk": fingerprint.pdk,
        "model": fingerprint.model,
        "simulator": fingerprint.simulator,
        "analysis": fingerprint.analysis,
        "va_sha256": fingerprint.va_sha256,
        "osdi_sha256": fingerprint.osdi_sha256,
    }
    fp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    ok_path.write_text("ok\n")


__all__ = [
    "JobFingerprint",
    "file_sha256",
    "fingerprint_digest",
    "should_skip",
    "write_cache",
]
