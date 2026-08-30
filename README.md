# acm-fit — LASCAS open release

End-to-end Python pipeline for compact-model parameter fitting against PDK BSIM
and PTM reference curves. This release demonstrates the workflow on the public
**ACM-5** (UFSC ACM2) Verilog-A model.

## Pipeline

```text
golden capture (BSIM Id–Vg)
    → automated DC fit (Optuna + refine)
    → predict benches (DC/AC/noise/temp/transient)
    → eval vs golden (optional)
    → SUMMARY.md + per-model REPORT.md
```

## Layout

```text
publications/release/lascas/
├── config/
│   ├── golden_suite_commercial.json   # sky130 + gf180mcu corners
│   ├── golden_suite_ptm.json          # PTM 180nm–22nm (no PDK install)
│   ├── eval_suite.json
│   ├── acm_tier_spec.json             # ACM-5 registry
│   └── pdk_env.example.json
├── models/acm5/                       # UFSC ACM2 Verilog-A
├── scripts/                           # run_all.sh, pipeline drivers
├── src/                               # synced from monorepo src/
└── results/<lane>/                    # generated artifacts
```

## Quick start

### 1. Dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Requires **ngspice** on `PATH`.

### 2. PDK / model paths

```bash
cp config/pdk_env.example.json config/pdk_env.local.json
# Edit SKY130_LIB, GF180_MODELS_DIR, SMC_ROOT
```

For PTM-only runs (no foundry PDK install):

```bash
git clone https://github.com/SJTU-YONGFU-RESEARCH-GRP/spice_model_collections.git \
  vendor/spice_model_collections
```

### 3. Run

```bash
# Commercial open PDKs with process corners (tt/ss/ff, typical/ss/ff)
bash scripts/run_all.sh commercial

# PTM technology scaling (ngspice only)
bash scripts/run_all.sh ptm

# Optional: add --eval for ACM vs BSIM eval suite (typical corners)
bash scripts/run_all.sh commercial --eval
```

### Paper figures

```bash
python3 scripts/plot_paper_figures.py   # writes figures/
```

Outputs land in `results/<lane>/SUMMARY.md`.

### Smoke test (no PDK install)

```bash
bash scripts/run_smoke.sh
```

Or manually:

```bash
export SMC_ROOT=/path/to/spice_model_collections
python3 scripts/run_golden_pipeline.py \
  --config config/golden_suite_smoke.json \
  --results-dir results/smoke \
  --iterations 5 \
  --simulators ngspice
```

## Process corners

`golden_suite_commercial.json` expands each PDK into corner targets:

| PDK | Targets |
|-----|---------|
| sky130 | `sky130_tt`, `sky130_ss`, `sky130_ff` |
| gf180mcu | `gf180mcu_typical`, `gf180mcu_ss`, `gf180mcu_ff` |

Each target gets its own BSIM golden capture and independent ACM-5 fit card.
After a commercial run, see `results/commercial/CORNER_REPORT.md` for a parameter
spread table (VT0, IS, n, σ, ζ vs corner).

## Sync from monorepo

Python sources are copied from the workspace `src/` tree:

```bash
bash scripts/sync_src.sh
```

Run this after changing `src/` in the monorepo so the release stays aligned.

## Registering another Verilog-A model

1. Add VA/OSDI under `models/<id>/`
2. Add a tier entry to `config/acm_tier_spec.json` (`module`, `va`, `osdi`, `dc_fit_params`)
3. List the model id in `fit_models` in the golden suite JSON

## License

Apache-2.0 for original code in this package. ACM-5 Verilog-A follows the UFSC
upstream license — see `models/acm5/`.

## Citation

```bibtex
@misc{AcmFitLascas2026,
  author = {Rokhani, Fakhrul Zaman and Low, Kain Lu and Li, Yongfu},
  title = {Automated Compact Model Fitting and Cross-Simulator Validation on Open PDKs},
  howpublished = {GitHub package \texttt{acm-fit}, tag v0.1.0-lascas-2026},
  year = {2026}
}
```

See `CITATION.cff` for machine-readable metadata.
