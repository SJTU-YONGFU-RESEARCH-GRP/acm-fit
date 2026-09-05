# acm-fit — LASCAS open release

[![License: CC BY 4.0](https://img.shields.io/badge/License-CC%20BY%204.0-green?logo=creativecommons&logoColor=white)](https://creativecommons.org/licenses/by/4.0/)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-3776ab.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/SJTU-YONGFU-RESEARCH-GRP/acm-fit/actions/workflows/smoke.yml/badge.svg)](https://github.com/SJTU-YONGFU-RESEARCH-GRP/acm-fit/actions/workflows/smoke.yml)

Open PDKs ship BSIM reference models, but fitting a design-oriented Verilog-A
compact model against them is still largely manual and hard to reproduce across
process corners. **acm-fit** closes that gap: frozen **BSIM golden Id–Vg
curves** for commercial open-PDK and PTM scaling targets, plus a headless
**Python pipeline** that extracts the public **ACM-5** (UFSC ACM2) model via
hybrid staged extraction and Optuna search, runs multi-analysis predict benches,
and reports structured ACM-vs-BSIM evaluation—or fits from your own Id–Vg CSVs
with no foundry netlist.

- **Repository:** [SJTU-YONGFU-RESEARCH-GRP/acm-fit](https://github.com/SJTU-YONGFU-RESEARCH-GRP/acm-fit)
- **Package name:** `acm-fit` (release tag `v0.1.0-lascas-2026`)
- **Related models:** [acm4](https://github.com/SJTU-YONGFU-RESEARCH-GRP/acm4), [qlaw](https://github.com/SJTU-YONGFU-RESEARCH-GRP/qlaw), [qlaw-discovery](https://github.com/SJTU-YONGFU-RESEARCH-GRP/qlaw-discovery)
- **Upstream PTM models:** [spice_model_collections](https://github.com/SJTU-YONGFU-RESEARCH-GRP/spice_model_collections) (git submodule)
- **Commercial PDKs:** sky130 and GF180MCU (install locally; not redistributed)
- **Entry points:** `scripts/run_all.sh` (all lanes + BYOD), `scripts/run_golden_pipeline.sh`, `scripts/run_eval_suite.sh`
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
- [Bring your own Id–Vg data](#bring-your-own-idvg-data)
  - [What you need](#what-you-need)
  - [Prepare your dataset](#prepare-your-dataset)
  - [Configure the custom suite](#configure-the-custom-suite)
  - [Run fitting](#run-fitting)
  - [Understand the outputs](#understand-the-outputs)
  - [Bundled robustness examples](#bundled-robustness-examples)
- [Dataset](#dataset)
  - [Frozen inputs (`data/golden/`)](#frozen-inputs-datagolden)
  - [Annotation schema](#annotation-schema)
  - [Import and export](#import-and-export)
- [Generated outputs (`results/`)](#generated-outputs-results)
- [Pipeline](#pipeline)
  - [Lanes and targets](#lanes-and-targets)
  - [Process corners](#process-corners)
  - [DC fit strategies](#dc-fit-strategies)
  - [Parallelism](#parallelism)
- [Benchmarks and figures](#benchmarks-and-figures)
- [Shell script reference](#shell-script-reference)
  - [Orchestration](#orchestration)
  - [Environment](#environment)
  - [Golden data I/O](#golden-data-io)
  - [Bring-your-own helpers](#bring-your-own-helpers)
  - [Maintenance and figures](#maintenance-and-figures)
- [Project layout](#project-layout)
- [Registering another Verilog-A model](#registering-another-verilog-a-model)
- [Sync from monorepo](#sync-from-monorepo)
- [License](#license)
- [Citation](#citation)

## TL;DR

**Bring your own data?** See [Bring your own Id–Vg data](#bring-your-own-idvg-data) — fit ACM-5
from your Id–Vg CSVs with `bash scripts/run_all.sh custom` (no PDK required).

**Data (frozen fit targets, in-repo)**

| Lane | Path | Targets | Curves per target | Points per curve |
|------|------|---------|-------------------|------------------|
| Commercial corners | `data/golden/commercial/` | 6 | 3 Id–Vg at VDS = 5%, 50%, 100% of VDD | 37 (Vg step 50 mV) |
| PTM scaling | `data/golden/ptm/` | 7 (`ptm180`…`ptm22`) | 3 Id–Vg | 37 |

Each target directory contains `meta.json` plus `idvg_vds_*.csv` files (`vg`, `id_ref` columns).

**Pipeline / scripts**

- Golden capture (BSIM via ngspice) → Optuna DC fit + refine → predict benches (DC/AC/noise/transient/temp) → eval vs BSIM → `SUMMARY.md` / `REPORT.md`
- Default run: **commercial**, **ptm**, and **custom** lanes (eval on PDK/PTM; custom runs the 8-example robustness matrix from `data/examples/`)
- Model demonstrated: **ACM-5** only in this release

## Features

- Automated **Id–Vg golden capture** from ngspice + PDK BSIM or PTM cards
- **Optuna** search with post-fit refine for ACM DC parameters
- **Three DC fit strategies** (`optuna`, `staged`, `staged_optuna`; default `staged_optuna`) plus optional **strategy benchmark** mode
- **Multi-analysis predict** and **ACM-vs-BSIM eval** with cached jobs
- **Corner expansion** for sky130 and GF180MCU (`tt`/`ss`/`ff`)
- **PTM technology scaling** lane (180 nm–22 nm) without a foundry PDK install
- Frozen golden dataset for fit-only reproduction (`--frozen-golden`)
- **Bring your own Id–Vg** — fit ACM-5 from user CSVs without a PDK (`custom` lane)
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
# All lanes (commercial + ptm + custom) + eval on PDK/PTM
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

CI runs the **full custom robustness matrix** (8 targets in `data/examples/`) with
reduced fit iterations. No foundry PDK required — only ngspice and Python deps.

```bash
bash scripts/run_smoke.sh
```

Output: `results/custom/SUMMARY.md` (same folder as `bash scripts/run_all.sh custom`).

Equivalent manual run with more control:

```bash
bash scripts/run_all.sh custom --iterations 5 --skip-predict --jobs 2
```

### Use frozen golden data

Skip live BSIM capture and fit from committed reference curves:

```bash
bash scripts/run_all.sh commercial --frozen-golden
bash scripts/run_all.sh ptm --frozen-golden --skip-eval
```

Eval still needs live PDK/PTM models to regenerate BSIM reference waveforms under `results/<lane>/golden/<pdk>/ref/`.

## Bring your own Id–Vg data

Fit ACM-5 against **your** reference curves — simulator export, TCAD, bench data, or any
tabular Id–Vg — **without** a foundry PDK install. Only DC Id–Vg CSVs are required for
the fit step; the pipeline can still run ACM-only predict benches (AC, noise, temperature,
transient) from the fitted card.

Full reference: [data/BRING_YOUR_OWN.md](data/BRING_YOUR_OWN.md).

### What you need

| Item | Required? | Notes |
|------|-----------|-------|
| Id–Vg CSV files | **Yes** | One file per \|VDS\| sweep; columns `vg`, `id_ref` |
| `meta.json` per target | **Yes** | Device geometry, VDD, sweep metadata |
| Suite JSON entry | **Yes** | `"data_only": true` — no BSIM netlist fields |
| PDK / ngspice BSIM | No | Not needed for custom-lane fit |
| 3 VDS sweeps | Recommended | 5% / 50% / 100% of VDD gives best DC fit; 1–2 sweeps also work |

**Minimum example:** one saturation Id–Vg at VDS = VDD (see `data/examples/custom_1vds_sat/`).
**Recommended:** three sweeps at low, mid, and high VDS (see `data/examples/custom_3vds_std/`).

### Prepare your dataset

Create one directory per device or corner under `data/golden/custom/<target>/`:

```text
data/golden/custom/my_device/
├── meta.json
├── idvg_vds_0p09.csv    # |VDS| = 0.09 V
├── idvg_vds_0p9.csv
└── idvg_vds_1p8.csv
```

**CSV format** (header required, drain current in amperes):

```csv
vg,id_ref
0,1.92e-13
0.05,7.04e-13
```

**Option A — convert arbitrary exports** (your CSV may use any `vg` / `id` column names):

```bash
bash scripts/convert_csv_golden.sh \
  --out data/golden/custom/my_device \
  --pdk my_device --vdd 1.8 --width-m 3e-6 --length-m 180e-9 \
  --curve 0.09:imports/idvg_low.csv \
  --curve 0.9:imports/idvg_mid.csv \
  --curve 1.8:imports/idvg_high.csv
```

**Option B — scaffold `meta.json`**, then copy files with the expected names:

```bash
bash scripts/scaffold_golden_target.sh \
  --out data/golden/custom/my_device \
  --pdk my_device --vdd 1.8 --width-m 3e-6 --length-m 180e-9 \
  --vds 0.09,0.9,1.8
# copy your CSVs into that directory, then:
bash scripts/validate_golden.sh data/golden/custom/my_device
```

**Naming rules**

| Field | Rule |
|-------|------|
| Target folder name | Must match the key in `golden_suite_*.json` → `targets` |
| `meta.json` → `pdk` | Same string as the target key |
| `meta.json` → `vds_list` | Absolute \|VDS\| in volts |
| `meta.json` → `vg_start`, `vg_step` | Gate sweep metadata (used when your grid is non-uniform) |
| CSV filename | `idvg_vds_<vds>.csv` with `.` → `p` (e.g. `0.9` → `idvg_vds_0p9.csv`) |
| PMOS | Prefix CSV names with `pmos_` and set `"polarity": "pmos"` in `meta.json` |

Set `"source": "user_supplied"` in `meta.json` so `SUMMARY.md` records provenance.

### Configure the custom suite

Copy the example config and add one `data_only` block per target folder:

```bash
cp config/golden_suite_custom.example.json config/golden_suite_custom.json
```

```json
"my_device": {
  "data_only": true,
  "vdd": 1.8,
  "width_m": 3.0e-6,
  "length_m": 1.8e-7,
  "polarity": "nmos"
}
```

`data_only` targets do **not** need `ngspice_section` or `ref_device`. Geometry and VDD
must match `meta.json`.

### Run fitting

**One command** (imports `data/golden/custom/`, fits, writes reports; eval is skipped):

```bash
bash scripts/run_all.sh custom
```

Useful options:

```bash
# Your data lives elsewhere
bash scripts/run_all.sh custom --golden-from /path/to/my_goldens

# Explicit suite file
bash scripts/run_all.sh custom --config config/golden_suite_custom.json

# Faster iteration
bash scripts/run_all.sh custom --iterations 50 --skip-predict --jobs 4
```

**Step by step** (same result, more control):

```bash
bash scripts/import_golden_data.sh --from data/golden/custom --to results/custom
bash scripts/run_golden_pipeline.sh \
  --config config/golden_suite_custom.json \
  --results-dir results/custom \
  --skip-golden --jobs 4
```

When you run `bash scripts/run_all.sh` (lane `all` or `custom`), the custom lane
uses `data/examples/` (8 targets) and writes to **`results/custom/`**. For your own
data under `data/golden/custom/`, pass `--golden-from data/golden/custom`.

### Understand the outputs

| Artifact | Custom lane |
|----------|-------------|
| `results/custom/acm5/fit/<target>.json` | Fitted ACM-5 parameters + fit metrics |
| `results/custom/acm5/fit/<target>_idvg_fit.png` | Your Id–Vg vs fitted ACM overlay |
| `results/custom/acm5/benches/...` | ACM-only DC/AC/noise/temp/transient waveforms |
| `results/custom/SUMMARY.md` | Cross-target fit errors and provenance table |
| `results/custom/acm5/REPORT.md` | Per-model detail |

Eval (ACM vs BSIM RMSE) is **not** run on the custom lane because there is no BSIM
reference for arbitrary user data. The fitted card is still used to **predict** AC,
noise, temperature, and transient benches via ngspice.

### Bundled robustness examples

Eight committed corpora under `data/examples/` exercise 1/2/3 VDS sets, sparse Vg grids,
short-channel nodes, and process corners. See [data/examples/README.md](data/examples/README.md).

```bash
bash scripts/validate_golden.sh data/examples/custom_3vds_std
bash scripts/run_all.sh custom --golden-from data/examples \
  --config config/golden_suite_custom.example.json
```

Regenerate examples from frozen BSIM goldens: `bash scripts/build_custom_examples.sh`.

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

See [Bring your own Id–Vg data](#bring-your-own-idvg-data) for fitting against user-supplied curves.

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
    → automated DC fit (strategy: staged_optuna by default)
    → predict benches (DC / AC / noise / transient / temp)
    → eval vs golden (default; --skip-eval to omit)
    → SUMMARY.md + per-model REPORT.md
```

### Lanes and targets

| Lane | Config | Eval config | Default eval PDKs |
|------|--------|-------------|-------------------|
| `commercial` | `config/golden_suite_commercial.json` | `config/eval_suite.json` | `sky130_tt`, `gf180mcu_typical` |
| `ptm` | `config/golden_suite_ptm.json` | `config/eval_suite_ptm.json` | `ptm180`…`ptm22` (all 7) |
| `custom` | `config/golden_suite_custom.example.json` (default) or `golden_suite_custom.json` (BYOD) | — (fit-only) | Default: `data/examples/` (8 targets) → `results/custom/` |

### Process corners

`golden_suite_commercial.json` expands each base PDK into corner targets:

| Base PDK | Fit / golden targets |
|----------|----------------------|
| sky130 | `sky130_tt`, `sky130_ss`, `sky130_ff` |
| gf180mcu | `gf180mcu_typical`, `gf180mcu_ss`, `gf180mcu_ff` |

Each target gets an independent BSIM golden capture and ACM-5 fit card.

### DC fit strategies

DC parameter extraction is configured in `fit_engine` inside each `config/golden_suite_*.json`. The staged recipe for ACM-5 lives in `config/fit_profiles/acm5_staged.json` (weak-inversion → $I_S$ → $\sigma$ → $\zeta$ stages with per-stage curve selectors).

| Strategy | Algorithm | When to use |
|----------|-----------|-------------|
| **`staged_optuna`** (default) | Design-oriented stages → narrow-box Optuna TPE → L-BFGS-B refine | Best accuracy on multi-$V_{DS}$ goldens; used for all paper benchmarks |
| `staged` | Design-oriented stages → L-BFGS-B refine only | Faster when Optuna budget is small (`optuna_trials` ≤ 15) |
| `optuna` | Full-space Optuna TPE → L-BFGS-B refine | Baseline global search without physics-informed staging |
| `benchmark` | Run a comma list from `fit_engine.strategies` and keep the lowest weighted error | Compare strategies on your golden before locking a default |

Suite JSON example:

```json
"fit_engine": {
  "strategy": "staged_optuna",
  "strategies": ["optuna", "staged", "staged_optuna"],
  "fit_profile": "acm5_staged",
  "optuna_box_fraction": 0.2
}
```

CLI overrides (passed through `run_all.sh` and `run_golden_pipeline.sh`):

```bash
# Force one strategy
bash scripts/run_all.sh commercial --fit-strategy staged

# Compare all three on one lane; writes results/<lane>/FIT_BENCHMARK.md
bash scripts/run_all.sh custom --fit-benchmark optuna,staged,staged_optuna --iterations 25 --skip-predict
```

Per-target breakdown: `results/<lane>/acm5/fit_benchmark/<target>.md`.

### Parallelism

`--jobs N` (default 4, or `JOBS` env var) limits concurrent ngspice workers across golden capture, fit, predict benches, eval golden refs, and eval jobs. Use `--jobs 1` for deterministic debugging.

## Benchmarks and figures

Frozen benchmark tables: [BENCHMARK.md](BENCHMARK.md).

After a full run (`bash scripts/run_all.sh` with commercial **and** ptm lanes),
paper summary figures are written automatically to `figures/fig_*.png`
(corner spread, PTM scaling, Id–Vg overlay, pipeline diagram). Per-target fit
and eval plots are always under `results/<lane>/acm5/`.

To regenerate `figures/` alone (e.g. after editing `plot_style.py`):

```bash
bash scripts/plot_paper_figures.sh
```

| Figure | File |
|--------|------|
| Pipeline diagram | `figures/fig_pipeline.png` |
| Id–Vg overlay (sky130_tt) | `figures/fig_idvg_sky130_tt.png` |
| Corner parameter spread | `figures/fig_corner_params.png` |
| PTM scaling error | `figures/fig_ptm_scaling.png` |

## Shell script reference

All drivers live under `scripts/`. They set `PYTHONPATH=src` and call `python3 -m acm.cli.*`
(see `_acm_env.sh`). Reports (`SUMMARY.md`, `REPORT.md`, `CORNER_REPORT.md`) are written
automatically at the end of `run_golden_pipeline.sh` and `run_all.sh`.

### Orchestration

#### `run_all.sh` — full benchmark driver

Runs golden import/capture → fit → predict → eval → reports for one or more lanes.

```bash
bash scripts/run_all.sh [all|commercial|ptm|custom] [options]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--jobs N` | `4` (or `JOBS` env) | Max concurrent ngspice workers |
| `--iterations N` | `1000` (from suite `fit_loss.optuna_trials`) | Override Optuna TPE trials per DC fit |
| `--fit-strategy NAME` | `staged_optuna` (from suite `fit_engine.strategy`) | `optuna`, `staged`, or `staged_optuna` |
| `--fit-benchmark LIST` | off | Compare strategies (`optuna,staged,staged_optuna`); writes `FIT_BENCHMARK.md` |
| `--frozen-golden` | off | Import `data/golden/<lane>/`, skip BSIM capture |
| `--golden-from DIR` | custom lane only | Import user goldens from `DIR` |
| `--config FILE` | custom lane only | Suite JSON (default `golden_suite_custom.json`) |
| `--skip-golden` | off | Use existing `results/<lane>/golden/` |
| `--skip-fit` | off | Skip Optuna fit |
| `--skip-predict` | off | Skip ACM predict benches |
| `--skip-eval` | off | Skip ACM vs BSIM eval |
| `--skip-figures` | off | Skip `figures/` regeneration (commercial + ptm results required) |
| `--force` | off | Re-run cached eval jobs |

**Examples**

```bash
bash scripts/run_all.sh                              # commercial + ptm + custom (8 examples)
bash scripts/run_all.sh commercial --frozen-golden   # fit from frozen BSIM Id–Vg
bash scripts/run_all.sh custom --iterations 50       # fewer trials for a quick BYOD run
bash scripts/run_all.sh ptm --skip-eval --jobs 8
```

#### `run_fit_benchmark.sh` — compare DC fit strategies

Runs `optuna`, `staged`, and `staged_optuna` on a lane (default: `custom` with frozen goldens) and writes `results/<lane>/FIT_BENCHMARK.md`.

```bash
bash scripts/run_fit_benchmark.sh custom --iterations 25 --jobs 2
bash scripts/run_fit_benchmark.sh commercial --strategies optuna,staged,staged_optuna
```

Custom-lane notes:

- Default: `data/examples/` (8 robustness targets) + `golden_suite_custom.example.json` → `results/custom/`.
- Your BYOD data: `bash scripts/run_all.sh custom --golden-from data/golden/custom`.
- Eval is always skipped on the custom lane.

#### `run_golden_pipeline.sh` — golden → fit → predict → reports

Lower-level driver when you already have goldens under `results/<lane>/golden/`.

```bash
bash scripts/run_golden_pipeline.sh \
  --config config/golden_suite_commercial.json \
  --results-dir results/commercial \
  --iterations 1000 \
  --jobs 4 \
  --simulators ngspice
```

| Flag | Description |
|------|-------------|
| `--skip-golden` | Skip BSIM capture (use existing `results/.../golden/`) |
| `--skip-fit` | Skip Optuna fit |
| `--skip-predict` | Skip predict benches |
| `--openvaf-binary` | Path to OpenVAF (default `work/openvaf-r`) |

Equivalent: `PYTHONPATH=src python3 -m acm.cli.pipeline`.

#### `run_eval_suite.sh` — ACM vs BSIM eval only

Runs after a fit when fitted cards and BSIM reference waveforms exist.

```bash
bash scripts/run_eval_suite.sh \
  --config config/eval_suite.json \
  --results-dir results/commercial \
  --models acm5 \
  --pdks sky130_tt,gf180mcu_typical \
  --simulators ngspice \
  --jobs 4 \
  --force
```

Normally invoked by `run_all.sh`; use standalone to re-eval without re-fitting.

#### `run_smoke.sh` — fast CI check (custom lane)

Runs the full 8-target custom robustness matrix with `--iterations 5` and
`--skip-predict`. No foundry PDK required. Used by `.github/workflows/smoke.yml`.

```bash
bash scripts/run_smoke.sh
# → results/custom/SUMMARY.md
```

### Environment

#### `setup_env.sh`

Verifies ngspice OSDI support and downloads/compiles OpenVAF into `work/openvaf-r`.
Called automatically by `run_all.sh` and `run_smoke.sh`; run manually after a fresh clone:

```bash
bash scripts/setup_env.sh
```

#### `load_pdk_env.sh`

Sources environment variables from `config/pdk_env.local.json` (`SKY130_LIB`,
`GF180_MODELS_DIR`, `SMC_ROOT`). Sourced by orchestration scripts — not usually run alone.

### Golden data I/O

#### `import_golden_data.sh`

Copy committed or user goldens into a results tree.

```bash
# Frozen lane → results/<lane>/golden/
bash scripts/import_golden_data.sh commercial
bash scripts/import_golden_data.sh ptm [optional_results_root]

# Arbitrary source directory
bash scripts/import_golden_data.sh --from data/golden/custom --to results/custom
bash scripts/import_golden_data.sh --from data/examples --to results/custom
```

Copies `meta.json` and `idvg_vds_*.csv` only.

#### `export_golden_data.sh`

Refresh committed frozen goldens after a new BSIM capture run.

```bash
bash scripts/run_all.sh commercial --skip-fit --skip-predict   # capture only
bash scripts/export_golden_data.sh commercial                  # → data/golden/commercial/
```

### Bring-your-own helpers

#### `scaffold_golden_target.sh`

Create `meta.json` and print expected CSV filenames for a new target.

```bash
bash scripts/scaffold_golden_target.sh \
  --out data/golden/custom/my_device \
  --pdk my_device --vdd 1.8 --width-m 3e-6 --length-m 180e-9 \
  --vds 0.09,0.9,1.8 \
  --polarity nmos \
  --vg-start 0.0 --vg-step 0.05
```

Optional: `--base-pdk`, `--corner`, `--force`.

#### `convert_csv_golden.sh`

Import generic `vg`/`id` CSV exports into the golden layout (one `--curve` per VDS).

```bash
bash scripts/convert_csv_golden.sh \
  --out data/golden/custom/my_device \
  --pdk my_device --vdd 1.8 --width-m 3e-6 --length-m 180e-9 \
  --curve 0.09:path/to/low_vds.csv \
  --curve 1.8:path/to/high_vds.csv
```

#### `validate_golden.sh`

Check `meta.json`, CSV headers, curve count, and point consistency.

```bash
bash scripts/validate_golden.sh data/golden/custom/my_device
bash scripts/validate_golden.sh data/examples/custom_3vds_std
```

#### `build_custom_examples.sh`

Regenerate the eight `data/examples/custom_*` robustness corpora from frozen BSIM goldens
and refresh `config/golden_suite_custom.example.json`.

```bash
bash scripts/build_custom_examples.sh
```

### Maintenance and figures

#### `clean.sh`

Remove generated artifacts (keeps `config/`, `models/`, `vendor/`, `figures/`, `.venv/`).

```bash
bash scripts/clean.sh                 # remove work/ + all results/<lane>/
bash scripts/clean.sh commercial      # one lane only
bash scripts/clean.sh --pycache       # also strip __pycache__ under src/
```

#### `plot_paper_figures.sh`

Regenerate LASCAS **paper summary** figures in `figures/` from `results/commercial`
and `results/ptm`. Called automatically at the end of `run_all.sh` when both lanes
have fit cards. Use standalone to refresh after style changes:

```bash
bash scripts/plot_paper_figures.sh
```

## Project layout

```text
.
├── config/                    # Suite policies and PDK env template
├── data/golden/               # Frozen BSIM Id–Vg (committed)
├── data/examples/             # BYOD robustness examples (custom lane)
├── data/BRING_YOUR_OWN.md     # Extended BYOD guide
├── figures/                   # Paper figures (committed)
├── src/acm/                   # Python package (golden, eval, opt, report, cli)
│   └── plot_style.py          # dev-plot palette (shared by all figures)
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
