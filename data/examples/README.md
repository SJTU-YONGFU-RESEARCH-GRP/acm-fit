# Custom-lane robustness examples

Committed Id–Vg corpora for the **custom** lane (`bash scripts/run_all.sh custom`).
Each folder is a self-contained `data_only` target (no BSIM capture).

Regenerate from frozen goldens:

```bash
bash scripts/build_custom_examples.sh
```

## Example matrix

| Target | # Vds sweeps | What it tests |
|--------|--------------|---------------|
| `custom_1vds_sat` | **1** (Vds = VDD) | Minimal data — saturation-only Id–Vg |
| `custom_2vds` | **2** (low + high) | Subthreshold + saturation without mid-Vds |
| `custom_3vds_std` | **3** (5% / 50% / 100% VDD) | Recommended user layout (PTM 180 nm) |
| `custom_sparse_vg` | **3**, coarse Vg step | Sparse gate sweep (every 4th point) |
| `custom_ptm22` | **3** | Short-channel 22 nm node, VDD = 0.95 V |
| `custom_sky130_ss` | **3** | sky130 **slow** corner (process/temp stress) |
| `custom_sky130_ff` | **3** | sky130 **fast** corner |
| `custom_gf180_typ` | **3** | GF180MCU typical, 3.3 V domain |

Sources are derived from `data/golden/ptm/` and `data/golden/commercial/` BSIM
captures, exported as user-style CSVs (`source: robustness_*` in `meta.json`).

## Default `run_all.sh` custom lane

`bash scripts/run_all.sh` (lane `all` or `custom`) runs the **full 8-target matrix**
from `data/examples/` into **`results/custom/`** with `golden_suite_custom.example.json`.

For your own corpus:

```bash
bash scripts/run_all.sh custom --golden-from data/golden/custom
```

Results: `results/custom/SUMMARY.md` — compare weighted error and Id–Vg overlays
across the matrix to assess fit robustness.

## Your own data

Add folders under `data/golden/custom/<target>/` and copy
`config/golden_suite_custom.example.json` → `config/golden_suite_custom.json`.
See [BRING_YOUR_OWN.md](BRING_YOUR_OWN.md).
