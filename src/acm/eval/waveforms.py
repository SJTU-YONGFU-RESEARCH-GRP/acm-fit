"""Common 2-column waveform I/O and Spectre/HSPICE ASCII parsers."""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np


def write_xy_csv(path: Path, x: np.ndarray, y: np.ndarray) -> None:
    """Write a 2-column ``x,y`` CSV with header."""
    if x.shape != y.shape or x.ndim != 1:
        raise ValueError(f"x/y shape mismatch: {x.shape} vs {y.shape}")
    if len(x) < 2:
        raise ValueError(f"need at least 2 points, got {len(x)}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        fh.write("x,y\n")
        for xi, yi in zip(x, y):
            fh.write(f"{float(xi):.12g},{float(yi):.12g}\n")


def load_xy_csv(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Load a 2-column ``x,y`` CSV written by :func:`write_xy_csv`."""
    if not path.is_file():
        raise FileNotFoundError(path)
    raw = np.loadtxt(path, delimiter=",", skiprows=1)
    if raw.ndim != 2 or raw.shape[1] < 2 or raw.shape[0] < 2:
        raise ValueError(f"expected Nx2 CSV in {path}, got {raw.shape}")
    return raw[:, 0], raw[:, 1]


def wrdata_to_xy(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Load ngspice ``wrdata`` (2+ columns) as ``(x, y)``.

    For multi-signal exports ngspice repeats the sweep variable in early
    columns; use column 0 for x and the last column for y.
    """
    raw = np.loadtxt(path)
    if raw.ndim != 2 or raw.shape[1] < 2 or raw.shape[0] < 2:
        raise ValueError(f"expected wrdata matrix in {path}, got {raw.shape}")
    if raw.shape[1] >= 3:
        return raw[:, 0], raw[:, -1]
    return raw[:, 0], raw[:, 1]


def parse_nutascii(
    path: Path,
    *,
    magnitude: bool = False,
    y_index: int | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Parse Spectre ``rawfmt=nutascii`` file into ``(x, y)``.

    Args:
        path: Path to ``.raw`` nutascii file.
        magnitude: If True and complex, take |y|.
        y_index: Preferred variable index for y. When the Values block has
            fewer floats than ``No. Variables``, the last available signal
            column is used.
    """
    if not path.is_file():
        raise FileNotFoundError(path)
    text = path.read_text(errors="ignore")
    n_pts_m = re.search(r"No\. Points:\s+(\d+)", text)
    if n_pts_m is None:
        raise ValueError(f"missing Points header in {path}")
    n_pts = int(n_pts_m.group(1))
    if n_pts < 2:
        raise ValueError(f"unsupported nutascii pts={n_pts}")

    var_block = text.split("Variables:", 1)[1].split("Values:", 1)[0]
    out_idx: int | None = None
    for line in var_block.splitlines():
        match = re.match(r"\s*(\d+)\s+(\S+)", line)
        if match and match.group(2) == "out":
            out_idx = int(match.group(1))
    if y_index is None:
        y_index = out_idx if out_idx is not None else None

    flags_complex = "Flags: complex" in text
    values_idx = text.find("Values:")
    if values_idx < 0:
        raise ValueError(f"missing Values section in {path}")
    tokens: list[str] = []
    for line in text[values_idx + len("Values:") :].splitlines():
        tokens.extend(re.split(r"[\s,]+", line.strip()))
    tokens = [t for t in tokens if t]

    # Split by point index tokens: integer i followed by floats for point i.
    point_starts: list[int] = []
    for i, tok in enumerate(tokens):
        if re.fullmatch(r"\d+", tok) and int(tok) == len(point_starts):
            point_starts.append(i)
            if len(point_starts) == n_pts:
                # continue scanning? stop once we have n_pts starts
                # but keep going to find end
                pass
    if len(point_starts) < n_pts:
        raise ValueError(
            f"found {len(point_starts)} point markers, expected {n_pts} in {path}"
        )
    point_starts = point_starts[:n_pts]
    ends = point_starts[1:] + [len(tokens)]

    xs: list[float] = []
    ys: list[float] = []
    for start, end in zip(point_starts, ends):
        chunk = tokens[start + 1 : end]
        if flags_complex:
            if len(chunk) % 2 != 0 or len(chunk) < 4:
                raise ValueError(f"bad complex chunk in {path}: {chunk[:8]}")
            pairs = [
                complex(float(chunk[i]), float(chunk[i + 1]))
                for i in range(0, len(chunk), 2)
            ]
            x_val = float(pairs[0].real)
            if y_index is not None and y_index < len(pairs):
                y_c = pairs[y_index]
            else:
                y_c = pairs[-1]
            y_val = abs(y_c) if magnitude else float(y_c.real)
        else:
            if len(chunk) < 2:
                raise ValueError(f"short real chunk in {path}: {chunk}")
            floats = [float(v) for v in chunk]
            x_val = floats[0]
            # y_index is among Variables (0=x). Signal columns are floats[1:].
            if y_index is not None and 0 < y_index < len(floats):
                y_val = floats[y_index]
            else:
                y_val = floats[-1]
            if magnitude:
                y_val = abs(y_val)
        xs.append(x_val)
        ys.append(float(y_val))
    return np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)


_HSPICE_SCALE = {
    "a": 1e-18,
    "f": 1e-15,
    "p": 1e-12,
    "n": 1e-9,
    "u": 1e-6,
    "m": 1e-3,
    "k": 1e3,
    "x": 1e6,  # HSPICE meg
    "g": 1e9,
    "t": 1e12,
}


def _parse_hspice_number(token: str) -> float:
    """Parse an HSPICE engineering-suffix number."""
    tok = token.strip().rstrip(".")
    if not tok:
        raise ValueError("empty HSPICE number token")
    match = re.match(
        r"^([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)([afpnumkxgt])?$",
        tok,
        flags=re.IGNORECASE,
    )
    if match is None:
        raise ValueError(f"unparseable HSPICE number: {token!r}")
    value = float(match.group(1))
    suf = match.group(2)
    if suf:
        value *= _HSPICE_SCALE[suf.lower()]
    return value


def parse_hspice_print_table(lis_path: Path, *, y_column: int = 1) -> tuple[np.ndarray, np.ndarray]:
    """Parse the ``x``…``y`` print table from an HSPICE ``.lis`` file."""
    if not lis_path.is_file():
        raise FileNotFoundError(lis_path)
    lines = lis_path.read_text(errors="ignore").splitlines()
    start = None
    end = None
    for idx, line in enumerate(lines):
        if line.strip() == "x":
            start = idx
        elif start is not None and line.strip() == "y":
            end = idx
            break
    if start is None or end is None or end <= start + 2:
        raise ValueError(f"missing HSPICE print table x..y in {lis_path}")
    data_lines: list[str] = []
    for line in lines[start + 1 : end]:
        stripped = line.strip()
        if not stripped:
            continue
        if re.match(r"^[+-]?\d", stripped):
            data_lines.append(stripped)
    if len(data_lines) < 2:
        raise ValueError(f"no numeric rows in HSPICE print table {lis_path}")
    xs: list[float] = []
    ys: list[float] = []
    for line in data_lines:
        parts = line.split()
        if len(parts) <= y_column:
            raise ValueError(f"short print row in {lis_path}: {line!r}")
        xs.append(_parse_hspice_number(parts[0]))
        ys.append(_parse_hspice_number(parts[y_column]))
    return np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)


def interpolate_to(
    x_ref: np.ndarray,
    x_src: np.ndarray,
    y_src: np.ndarray,
    *,
    span_tol: float = 0.02,
) -> np.ndarray:
    """Interpolate ``y_src(x_src)`` onto ``x_ref``; fail on large span mismatch."""
    if len(x_ref) < 2 or len(x_src) < 2:
        raise ValueError("interpolation requires >=2 points")
    ref_span = float(x_ref[-1] - x_ref[0])
    src_span = float(x_src[-1] - x_src[0])
    if ref_span == 0.0 or src_span == 0.0:
        raise ValueError("zero x-span in interpolation")
    lo = max(float(x_ref[0]), float(x_src[0]))
    hi = min(float(x_ref[-1]), float(x_src[-1]))
    overlap = hi - lo
    if overlap <= 0.0 or overlap / abs(ref_span) < (1.0 - span_tol):
        raise ValueError(
            f"x-span mismatch ref=[{x_ref[0]},{x_ref[-1]}] "
            f"src=[{x_src[0]},{x_src[-1]}]"
        )
    order = np.argsort(x_src)
    return np.interp(x_ref, x_src[order], y_src[order])


def ensure_hspice_va_path(va_path: Path, work_dir: Path) -> Path:
    """Return a lowercase-path symlink to ``va_path`` for HSPICE ``-hdl``."""
    if not va_path.is_file():
        raise FileNotFoundError(va_path)
    work_dir.mkdir(parents=True, exist_ok=True)
    link = work_dir / va_path.name.lower()
    target = va_path.resolve()
    if link.is_symlink() or link.exists():
        if link.resolve() != target:
            link.unlink()
            link.symlink_to(target)
    else:
        link.symlink_to(target)
    return link


def parse_nutascii_onoise(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Parse Spectre noise nutascii into onoise density (V/sqrt(Hz)).

    Spectre often lists ``out`` in the Variables header but only dumps the
    V^2/Hz contributor columns in Values. Reconstruct onoise as
    ``sqrt(sum(*.total V^2/Hz))``.
    """
    if not path.is_file():
        raise FileNotFoundError(path)
    text = path.read_text(errors="ignore")
    n_pts_m = re.search(r"No\. Points:\s+(\d+)", text)
    if n_pts_m is None:
        raise ValueError(f"missing Points header in {path}")
    n_pts = int(n_pts_m.group(1))
    var_block = text.split("Variables:", 1)[1].split("Values:", 1)[0]
    total_idxs: list[int] = []
    out_idx: int | None = None
    for line in var_block.splitlines():
        match = re.match(r"\s*(\d+)\s+(\S+)\s+(\S+)", line)
        if not match:
            continue
        idx = int(match.group(1))
        name = match.group(2)
        unit = match.group(3)
        if name == "out":
            out_idx = idx
        if name.endswith(".total") and "V^2" in unit:
            total_idxs.append(idx)
    values_idx = text.find("Values:")
    if values_idx < 0:
        raise ValueError(f"missing Values section in {path}")
    tokens: list[str] = []
    for line in text[values_idx + len("Values:") :].splitlines():
        tokens.extend(re.split(r"[\s,]+", line.strip()))
    tokens = [t for t in tokens if t]
    point_starts: list[int] = []
    for i, tok in enumerate(tokens):
        if re.fullmatch(r"\d+", tok) and int(tok) == len(point_starts):
            point_starts.append(i)
            if len(point_starts) >= n_pts:
                break
    if len(point_starts) < n_pts:
        raise ValueError(f"found {len(point_starts)} points, expected {n_pts}")
    ends = point_starts[1:] + [len(tokens)]
    xs: list[float] = []
    ys: list[float] = []
    for start, end in zip(point_starts[:n_pts], ends[:n_pts]):
        floats = [float(v) for v in tokens[start + 1 : end]]
        if len(floats) < 2:
            raise ValueError(f"short noise point in {path}")
        x_val = floats[0]
        if out_idx is not None and out_idx < len(floats):
            y_val = abs(floats[out_idx])
        elif total_idxs:
            dens = 0.0
            for idx in total_idxs:
                if idx < len(floats):
                    dens += max(floats[idx], 0.0)
            if dens <= 0.0:
                raise ValueError(f"non-positive noise density in {path}")
            y_val = float(np.sqrt(dens))
        else:
            raise ValueError(f"no out/.total noise columns in {path}")
        xs.append(x_val)
        ys.append(y_val)
    return np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)


__all__ = [
    "write_xy_csv",
    "load_xy_csv",
    "wrdata_to_xy",
    "parse_nutascii",
    "parse_nutascii_onoise",
    "parse_hspice_print_table",
    "interpolate_to",
    "ensure_hspice_va_path",
]
