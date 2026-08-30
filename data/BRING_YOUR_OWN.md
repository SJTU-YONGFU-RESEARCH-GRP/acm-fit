# Bring your own golden data (Id–Vg)

Fit ACM models against **your** reference curves without running BSIM capture.

## Quick path (3 steps)

### 1. Prepare one target directory per device/corner

**Option A — convert generic CSV files** (any `vg` / `id` column headers):

```bash
python3 scripts/convert_csv_golden.py \
  --out data/golden/custom/my_chip_tt \
  --pdk my_chip_tt --vdd 1.8 --width-m 3e-6 --length-m 180e-9 \
  --curve 0.09:imports/idvg_low_vds.csv \
  --curve 0.9:imports/idvg_mid_vds.csv \
  --curve 1.8:imports/idvg_high_vds.csv
```

**Option B — scaffold** then copy pre-named CSVs:

Each target is a folder with `meta.json` plus one CSV per $|V_{DS}|$ sweep:

```text
data/golden/custom/my_chip_tt/
├── meta.json
├── idvg_vds_0p09.csv    # |VDS| = 0.09 V
├── idvg_vds_0p9.csv
└── idvg_vds_1p8.csv
```

CSV format (header required):

```csv
vg,id_ref
0,1.92e-13
0.05,7.04e-13
```

Use the scaffold helper to create `meta.json` and see expected filenames:

```bash
python3 scripts/scaffold_golden_target.py \
  --out data/golden/custom/my_chip_tt \
  --pdk my_chip_tt \
  --vdd 1.8 \
  --width-m 3e-6 \
  --length-m 180e-9 \
  --vds 0.09,0.9,1.8
# copy your CSVs into that directory, then:
PYTHONPATH=src python3 scripts/validate_golden.py data/golden/custom/my_chip_tt
```

Copy `config/golden_suite_custom.example.json` → `config/golden_suite_custom.json` and add a `data_only` target for each folder name:

```json
"my_chip_tt": {
  "data_only": true,
  "vdd": 1.8,
  "width_m": 3.0e-6,
  "length_m": 1.8e-7,
  "polarity": "nmos"
}
```

`data_only` targets **do not** need `ngspice_section` or `ref_device`.

### 2. One-command fit

```bash
cp config/golden_suite_custom.example.json config/golden_suite_custom.json
# edit targets in config/golden_suite_custom.json if needed

bash scripts/run_all.sh custom
```

This imports `data/golden/custom/` → `results/custom/`, fits ACM-5, and writes reports. Eval is skipped (no BSIM reference for arbitrary user data).

Options: `--golden-from <dir>`, `--config <json>`, `--iterations N`, `--skip-predict`.

### 3. Step-by-step (optional)

```bash
bash scripts/import_golden_data.sh --from data/golden/custom --to results/custom
PYTHONPATH=src python3 scripts/run_golden_pipeline.py \
  --config config/golden_suite_custom.json \
  --results-dir results/custom \
  --skip-golden --jobs 4
```

Outputs: `results/custom/acm5/fit/<target>.json`, `SUMMARY.md`.

## Where data can come from

| Source | How to get into acm-fit |
|--------|-------------------------|
| **Your simulator export** | Format as `vg,id_ref` CSVs + `meta.json` (scaffold script) |
| **Our frozen sets** | Use `data/golden/commercial/` or `ptm/` as-is |
| **BSIM capture** | Full pipeline with PDK paths (no `data_only`) |
| **TCAD / measured data** | Same CSV layout; set `"source": "user_supplied"` in meta |

## Naming rules

| Field | Rule |
|-------|------|
| Target folder name | Must match the key in `golden_suite_*.json` `targets` |
| `meta.json` → `pdk` | Same string as target key |
| `meta.json` → `vds_list` | Absolute $|V_{DS}|$ in volts; order defines curves |
| CSV filename | `idvg_vds_<vds>.csv` with `.` → `p` (e.g. `0.9` → `idvg_vds_0p9.csv`) |
| PMOS | Prefix CSV names with `pmos_` and set `"polarity": "pmos"` |

## Example in this repo

`data/examples/demo_nmos/` — minimal valid layout (copied from PTM 180 nm golden). Try:

```bash
PYTHONPATH=src python3 scripts/validate_golden.py data/examples/demo_nmos

# Quick end-to-end (copy example into custom lane)
mkdir -p data/golden/custom
cp -r data/examples/demo_nmos data/golden/custom/
cp config/golden_suite_custom.example.json config/golden_suite_custom.json
bash scripts/run_all.sh custom
```

## Eval with your data

Post-fit **eval** still needs BSIM (or PTM) models to build `golden/<pdk>/ref/` waveforms. For fit-only workflows, use `--skip-eval` or omit the eval step.
