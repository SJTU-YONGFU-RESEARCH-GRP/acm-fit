# acm-fit — LASCAS open release

[![License: CC BY 4.0](https://img.shields.io/badge/License-CC%20BY%204.0-green?logo=creativecommons&logoColor=white)](https://creativecommons.org/licenses/by/4.0/)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-3776ab.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/SJTU-YONGFU-RESEARCH-GRP/acm-fit/actions/workflows/smoke.yml/badge.svg)](https://github.com/SJTU-YONGFU-RESEARCH-GRP/acm-fit/actions/workflows/smoke.yml)

This repository provides **frozen BSIM reference I–V curves** for open PDK and PTM
nodes and an **end-to-end Python pipeline** that fits the public **ACM-5** (UFSC
ACM2) Verilog-A compact model, runs predict benches, and evaluates ACM vs BSIM
golden waveforms.

- **Repository:** [SJTU-YONGFU-RESEARCH-GRP/acm-fit](https://github.com/SJTU-YONGFU-RESEARCH-GRP/acm-fit)
- **Package name:** `acm-fit` (release tag `v0.1.0-lascas-2026`)
- **Upstream PTM models:** [spice_model_collections](https://github.com/SJTU-YONGFU-RESEARCH-GRP/spice_model_collections) (git submodule)
- **Commercial PDKs:** sky130 and GF180MCU (install locally; not redistributed)
- **Entry points:** `scripts/run_all.sh`, `scripts/run_golden_pipeline.sh`, `scripts/run_eval_suite.sh`
- **License:** CC BY 4.0 for this package (see [LICENSE](LICENSE)); ACM-5 Verilog-A under UFSC terms in `models/acm5/`

## Table of contents

- [TL;DR](#tldr)
- [Features](#features)
- [Requirements](#requirements)
- [Quick start](#quick-start)
  - [Install dependencies](#install-dependencies)
  - [Configure PDK paths](#configure-pdk-paths)
  - [Run the full benchmark](#run-the-full-benchmark)
  - [Smoke test without foundry PDKs](#smoke-test-without-foundry-pdks)
  - [Use frozen golden data](#use-frozen-golden-data)
- [Dataset](#dataset)
  - [Frozen inputs (`data/golden/`)](#frozen-inputs-datagolden)
  - [Annotation schema](#annotation-schema)
  - [Import and export](#import-and-export)
- [Generated outputs (`results/`)](#generated-outputs-results)
- [Pipeline](#pipeline)
  - [Lanes and targets](#lanes-and-targets)
  - [Process corners](#process-corners)
  - [Parallelism](#parallelism)
- [Benchmarks and figures](#benchmarks-and-figures)
- [CLI reference](#cli-reference)
- [Project layout](#project-layout)
- [Registering another Verilog-A model](#registering-another-verilog-a-model)
- [Sync from monorepo](#sync-from-monorepo)
- [License](#license)
- [Citation](#citation)

## TL;DR

**Data (frozen fit targets, in-repo)**

| Lane | Path | Targets | Curves per target | Points per curve |
|------|------|---------|-------------------|------------------|
| Commercial corners | `data/golden/commercial/` | 6 | 3 Id–Vg at VDS = 5%, 50%, 100% of VDD | 37 (Vg step 50 mV) |
| PTM scaling | `data/golden/ptm/` | 7 (`ptm180`…`ptm22`) | 3 Id–Vg | 37 |

Each target directory contains `meta.json` plus `idvg_vds_*.csv` files (`vg`, `id_ref` columns).

**Pipeline / scripts**

- Golden capture (BSIM via ngspice) → Optuna DC fit + refine → predict benches (DC/AC/noise/transient/temp) → eval vs BSIM → `SUMMARY.md` / `REPORT.md`
- Default run: **both** `commercial` and `ptm` lanes with eval enabled
- Model demonstrated: **ACM-5** only in this release

## Features

- Automated **Id–Vg golden capture** from ngspice + PDK BSIM or PTM cards
- **Optuna** search with post-fit refine for ACM DC parameters
- **Multi-analysis predict** and **ACM-vs-BSIM eval** with cached jobs
- **Corner expansion** for sky130 and GF180MCU (`tt`/`ss`/`ff`)
- **PTM technology scaling** lane (180 nm–22 nm) without a foundry PDK install
- Frozen golden dataset for fit-only reproduction (`--frozen-golden`)
- Parallel ngspice workers (`--jobs`, default 4)
- Paper figures and frozen benchmark tables (`figures/`, `BENCHMARK.md`)

## Requirements

| Component | Version / notes |
|-----------|-----------------|
| Python | 3.9+ |
| ngspice | **44+** on `PATH` (OSDI 0.4; Ubuntu apt `ngspice` is often too old) |
| Python packages | `numpy`, `scipy`, `matplotlib`, `optuna` — see [requirements.txt](requirements.txt) |
| OpenVAF | Downloaded automatically by `scripts/setup_env.sh` into `work/openvaf-r` |
| sky130 + GF180MCU | Required for **commercial** golden capture and eval (not bundled) |
| spice_model_collections | **Git submodule** at `vendor/spice_model_collections` (PTM lane) |

## Quick start

### Install dependencies

```bash
git submodule update --init --recursive   # PTM model cards

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

If you have not cloned with submodules yet:

```bash
git clone --recurse-submodules https://github.com/SJTU-YONGFU-RESEARCH-GRP/acm-fit.git
```

### Configure PDK paths

```bash
cp config/pdk_env.example.json config/pdk_env.local.json
```

Edit `config/pdk_env.local.json`:

| Variable | Used for |
|----------|----------|
| `SKY130_LIB` | sky130 ngspice `.lib` path |
| `GF180_MODELS_DIR` | GF180MCU ngspice model directory |
| `SMC_ROOT` | Root of [spice_model_collections](https://github.com/SJTU-YONGFU-RESEARCH-GRP/spice_model_collections) |

For PTM-only work (no foundry PDK install), initialize the submodule (if not done
above) and set `SMC_ROOT`:

```bash
git submodule update --init vendor/spice_model_collections
```

Set `"SMC_ROOT": "vendor/spice_model_collections"` in `pdk_env.local.json`.

### Run the full benchmark

```bash
# Both lanes + eval (default)
bash scripts/run_all.sh

# More parallel ngspice workers
bash scripts/run_all.sh --jobs 8
JOBS=8 bash scripts/run_all.sh

# Single lane
bash scripts/run_all.sh commercial
bash scripts/run_all.sh ptm

# Faster: skip eval
bash scripts/run_all.sh --skip-eval
```

Reports: `results/<lane>/SUMMARY.md` (and `results/commercial/CORNER_REPORT.md` after a commercial run).

### Smoke test without foundry PDKs

CI runs this path with only `SMC_ROOT` set (one PTM node, 5 Optuna trials):

```bash
bash scripts/run_smoke.sh
```

Output: `results/smoke/SUMMARY.md`.

### Use frozen golden data

Skip live BSIM capture and fit from committed reference curves:

```bash
bash scripts/run_all.sh commercial --frozen-golden
bash scripts/run_all.sh ptm --frozen-golden --skip-eval
```

Eval still needs live PDK/PTM models to regenerate BSIM reference waveforms under `results/<lane>/golden/<pdk>/ref/`.

## Dataset

### Frozen inputs (`data/golden/`)

Pre-captured **BSIM Id–Vg** reference curves used as DC fit targets. See also [data/README.md](data/README.md).

```text
data/golden/
├── commercial/                 # ~260 KB
│   ├── sky130_tt/
│   ├── sky130_ss/
│   ├── sky130_ff/
│   ├── gf180mcu_typical/
│   ├── gf180mcu_ss/
│   └── gf180mcu_ff/
└── ptm/                        # ~112 KB
    ├── ptm180/
    ├── ptm130/
    ├── ptm90/
    ├── ptm65/
    ├── ptm45/
    ├── ptm32/
    └── ptm22/
```

| Lane | Source simulator | Upstream models |
|------|------------------|-----------------|
| `commercial` | ngspice + open PDK BSIM | sky130A, GF180MCU (user-installed) |
| `ptm` | ngspice + PTM cards | `spice_model_collections/ptm/*.pm` |

### Annotation schema

**Per-target `meta.json`** (example from `data/golden/commercial/sky130_tt/meta.json`):

```json
{
  "pdk": "sky130_tt",
  "vdd": 1.8,
  "width_m": 3e-06,
  "length_m": 2.5e-07,
  "polarity": "nmos",
  "vg_start": 0.0,
  "vg_step": 0.05,
  "vds_list": [0.09, 0.9, 1.8],
  "n_points_per_curve": 37,
  "source": "pdk_bsim_ngspice",
  "role": "golden_iv_for_acm_dc_fit",
  "base_pdk": "sky130",
  "corner": "tt"
}
```

**Per-curve CSV** (`idvg_vds_<vds>.csv`):

```csv
vg,id_ref
0,1.92499243e-13
0.05,7.04058255e-13
```

Sweep policy is defined in `config/golden_suite_*.json` (`vg_start`, `vg_step`, `vds_fractions`).

### Import and export

```bash
# Copy frozen goldens into results/<lane>/golden/
bash scripts/import_golden_data.sh commercial
bash scripts/import_golden_data.sh ptm [optional_results_root]

# Refresh data/golden/ after a new capture run
bash scripts/export_golden_data.sh commercial
bash scripts/export_golden_data.sh ptm
```

### Bring your own Id–Vg data

You do **not** need a PDK install to fit against your own reference curves. Full guide: [data/BRING_YOUR_OWN.md](data/BRING_YOUR_OWN.md).

```bash
# 1. Scaffold meta.json (lists expected CSV filenames)
bash scripts/scaffold_golden_target.sh \
  --out data/golden/custom/my_device \
  --pdk my_device --vdd 1.8 --width-m 3e-6 --length-m 180e-9 \
  --vds 0.09,0.9,1.8

# 2. Add your vg,id_ref CSVs, then validate
bash scripts/validate_golden.sh data/golden/custom/my_device

# 3. Point config/golden_suite_custom.json at data_only targets (see example)
cp config/golden_suite_custom.example.json config/golden_suite_custom.json

# 4. One-command fit (imports data/golden/custom/, skips eval)
bash scripts/run_all.sh custom
```

Set `"data_only": true` on targets in the golden suite JSON so `ngspice_section` / `ref_device` are not required.

## Generated outputs (`results/`)

Pipeline outputs are written under `results/<lane>/` and are **gitignored** (regenerate locally or archive separately).

```text
results/<lane>/
├── SUMMARY.md
├── CORNER_REPORT.md              # commercial lane only
├── golden/<target>/
│   ├── meta.json + idvg_vds_*.csv   # DC fit goldens (same schema as data/golden/)
│   └── ref/<analysis>/ref.csv       # eval BSIM references (DC/AC/noise/transient/temp)
└── acm5/
    ├── fit/<target>.json            # fitted ACM parameter cards
    ├── fit/<target>_history.csv     # Optuna / refine trajectory
    ├── fit/error_vs_iteration.png
    ├── benches/<target>/<sim>/<analysis>/...
    ├── eval/<pdk>/<sim>/<analysis>/...   # metrics.json, acm.csv vs ref
    └── REPORT.md
```

| Artifact | Purpose |
|----------|---------|
| `fit/<target>.json` | Fitted ACM parameters + loss history metadata |
| `benches/` | ACM-only waveforms from fitted cards |
| `eval/` | ACM vs ngspice PDK-BSIM golden comparison |
| `SUMMARY.md` | Cross-target regression summary |

Remove generated trees with `bash scripts/clean.sh` (keeps `data/`, `vendor/`, `config/pdk_env.local.json`).

Frozen paper numbers without full `results/` trees: [BENCHMARK.md](BENCHMARK.md) and `figures/*.png`.

## Pipeline

```text
golden capture (BSIM Id–Vg)
    → automated DC fit (Optuna + refine)
    → predict benches (DC / AC / noise / transient / temp)
    → eval vs golden (default; --skip-eval to omit)
    → SUMMARY.md + per-model REPORT.md
```

### Lanes and targets

| Lane | Config | Eval config | Default eval PDKs |
|------|--------|-------------|-------------------|
| `commercial` | `config/golden_suite_commercial.json` | `config/eval_suite.json` | `sky130_tt`, `gf180mcu_typical` |
| `ptm` | `config/golden_suite_ptm.json` | `config/eval_suite_ptm.json` | `ptm180`…`ptm22` (all 7) |
| `custom` | `config/golden_suite_custom.json` | — (fit-only) | — |
| `smoke` | `config/golden_suite_smoke.json` | — | — |

### Process corners

`golden_suite_commercial.json` expands each base PDK into corner targets:

| Base PDK | Fit / golden targets |
|----------|----------------------|
| sky130 | `sky130_tt`, `sky130_ss`, `sky130_ff` |
| gf180mcu | `gf180mcu_typical`, `gf180mcu_ss`, `gf180mcu_ff` |

Each target gets an independent BSIM golden capture and ACM-5 fit card.

### Parallelism

`--jobs N` (default 4, or `JOBS` env var) limits concurrent ngspice workers across golden capture, fit, predict benches, eval golden refs, and eval jobs. Use `--jobs 1` for deterministic debugging.

## Benchmarks and figures

Frozen benchmark tables from the LASCAS paper runs: [BENCHMARK.md](BENCHMARK.md).

Regenerate figures from `results/`:

```bash
python3 scripts/plot_paper_figures.py
```

Outputs:

| Figure | File |
|--------|------|
| Pipeline diagram | `figures/fig_pipeline.png` |
| Id–Vg overlay (sky130_tt) | `figures/fig_idvg_sky130_tt.png` |
| Corner parameter spread | `figures/fig_corner_params.png` |
| PTM scaling error | `figures/fig_ptm_scaling.png` |

## CLI reference

### `scripts/run_all.sh`

```text
bash scripts/run_all.sh [all|commercial|ptm|custom] [options]

Options:
  --jobs N            Parallel ngspice workers (default 4)
  --iterations N      Optuna trials per fit (default 25)
  --frozen-golden     Import data/golden/<lane>/ then skip capture
  --golden-from DIR   Custom lane: import goldens from DIR (default data/golden/custom/)
  --config FILE       Custom lane: suite JSON (default config/golden_suite_custom.json)
  --skip-golden       Skip BSIM capture (use existing results/<lane>/golden/)
  --skip-fit          Skip Optuna fit
  --skip-predict      Skip predict benches
  --skip-eval         Skip ACM vs BSIM eval (eval is ON by default; custom lane skips eval)
  --eval              Force eval on (default)
  --force             Re-run cached eval jobs
```

### `scripts/run_golden_pipeline.sh`

```bash
bash scripts/run_golden_pipeline.sh \
  --config config/golden_suite_commercial.json \
  --results-dir results/commercial \
  --iterations 25 \
  --jobs 4 \
  --simulators ngspice
```

Equivalent: `python3 -m acm.cli.pipeline` (with `PYTHONPATH=src`).

Flags: `--skip-golden`, `--skip-fit`, `--skip-predict`, `--openvaf-binary work/openvaf-r`.

### `scripts/run_eval_suite.sh`

```bash
bash scripts/run_eval_suite.sh \
  --config config/eval_suite.json \
  --results-dir results/commercial \
  --models acm5 \
  --pdks sky130_tt,gf180mcu_typical \
  --simulators ngspice \
  --jobs 4
```

### Other scripts

| Script | Purpose |
|--------|---------|
| `scripts/setup_env.sh` | Fetch OpenVAF binary into `work/` |
| `scripts/load_pdk_env.sh` | Export env vars from `pdk_env.local.json` |
| `scripts/import_golden_data.sh` | Copy golden dirs → `results/` (`--from` / `--to` for custom paths) |
| `scripts/convert_csv_golden.sh` | Import generic `vg`/`id` CSVs into golden layout |
| `scripts/scaffold_golden_target.sh` | Create `meta.json` for a new user target |
| `scripts/validate_golden.sh` | Validate `meta.json` + CSV layout |
| `scripts/export_golden_data.sh` | Copy `results/<lane>/golden/` → `data/golden/` |
| `scripts/clean.sh` | Remove `results/*/` and `work/` |
| `scripts/plot_paper_figures.sh` | Regenerate `figures/` |
| `scripts/write_reports.sh` | Regenerate `SUMMARY.md` / `REPORT.md` from artifacts |

## Project layout

```text
.
├── config/                    # Suite policies and PDK env template
├── data/golden/               # Frozen BSIM Id–Vg (committed)
├── figures/                   # Paper figures (committed)
├── src/acm/                   # Python package (golden, eval, opt, report, cli)
├── models/acm5/               # UFSC ACM-5 Verilog-A + OSDI
├── scripts/                   # Shell drivers → python3 -m acm.cli.*
├── vendor/                    # spice_model_collections (git submodule)
├── work/                      # OpenVAF cache (gitignored)
├── results/                   # Generated outputs (gitignored)
├── BENCHMARK.md               # Frozen benchmark tables
├── CITATION.cff
├── LICENSE
├── PUBLISH.md
└── requirements.txt
```

## Registering another Verilog-A model

1. Add VA/OSDI under `models/<id>/`
2. Add a tier entry to `config/acm_tier_spec.json` (`module`, `va`, `osdi`, `dc_fit_params`)
3. List the model id in `fit_models` in the golden suite JSON

## License

- **Pipeline code, frozen golden data, and documentation** in this package: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) (see [LICENSE](LICENSE))
- **ACM-5 Verilog-A**: UFSC upstream license — see `models/acm5/`
- **PTM model cards**: terms of [spice_model_collections](https://github.com/SJTU-YONGFU-RESEARCH-GRP/spice_model_collections)
- **Foundry PDKs** (sky130, GF180MCU): follow each PDK's distribution license

## Citation

```bibtex
@misc{AcmFitLascas2026,
  author = {Rokhani, Fakhrul Zaman and Low, Kain Lu and Li, Yongfu},
  title = {Automated Compact Model Fitting and Cross-Simulator Validation on Open PDKs},
  howpublished = {GitHub package \texttt{acm-fit}, tag v0.1.0-lascas-2026},
  year = {2026}
}
```

Machine-readable metadata: [CITATION.cff](CITATION.cff). Update `repository-code` when the public GitHub URL is finalized.
