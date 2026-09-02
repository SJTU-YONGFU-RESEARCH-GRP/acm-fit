Full guide: [README.md — Bring your own Id–Vg data](README.md#bring-your-own-idvg-data).
Extended reference: this file.

## Quick path (3 steps)

### 1. Prepare one target directory per device/corner

**Option A — convert generic CSV files** (any `vg` / `id` column headers):

```bash
bash scripts/convert_csv_golden.sh \
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
bash scripts/scaffold_golden_target.sh \
  --out data/golden/custom/my_chip_tt \
  --pdk my_chip_tt \
  --vdd 1.8 \
  --width-m 3e-6 \
  --length-m 180e-9 \
  --vds 0.09,0.9,1.8
# copy your CSVs into that directory, then:
bash scripts/validate_golden.sh data/golden/custom/my_chip_tt
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

bash scripts/run_all.sh custom --golden-from data/golden/custom
```

This imports `data/golden/custom/` → `results/custom/`, fits ACM-5, and writes reports. Eval is skipped (no BSIM reference for arbitrary user data).

Options: `--golden-from <dir>`, `--config <json>`, `--iterations N`, `--skip-predict`.

### 3. Step-by-step (optional)

```bash
bash scripts/import_golden_data.sh --from data/golden/custom --to results/custom
bash scripts/run_golden_pipeline.sh \
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

Set `"source"` in `meta.json` so `SUMMARY.md` records dataset provenance. Reports adapt automatically:

| Input | Fit section | Waveform plots |
|-------|-------------|----------------|
| PDK / PTM BSIM (`bash scripts/run_all.sh commercial` or `ptm`) | Id–Vg vs BSIM + optimized params | DC Id–Vg overlay + eval vs BSIM (DC/AC/noise/temp/transient) + ACM-only predict benches |
| User CSV (`bash scripts/run_all.sh custom`) | Id–Vg vs your data + params | DC Id–Vg overlay + **ACM-only** AC/noise/temp/transient predict plots (no BSIM reference) |

The fitted ACM card is always used to **predict** DC/AC/noise/temperature/transient benches via ngspice, even when you only supplied Id–Vg CSVs. Eval (RMSE vs a reference) is skipped for custom input because there is no BSIM golden.

## Naming rules

| Field | Rule |
|-------|------|
| Target folder name | Must match the key in `golden_suite_*.json` `targets` |
| `meta.json` → `pdk` | Same string as target key |
| `meta.json` → `vds_list` | Absolute $|V_{DS}|$ in volts; order defines curves |
| CSV filename | `idvg_vds_<vds>.csv` with `.` → `p` (e.g. `0.9` → `idvg_vds_0p9.csv`) |
| PMOS | Prefix CSV names with `pmos_` and set `"polarity": "pmos"` |

## Example in this repo

See **[data/examples/README.md](examples/README.md)** — eight robustness targets (1/2/3 Vds, sparse Vg, PTM 22 nm, sky130 corners, GF180).

```bash
bash scripts/build_custom_examples.sh   # regenerate from frozen goldens
bash scripts/validate_golden.sh data/examples/custom_3vds_std

# Full robustness matrix (default custom lane → results/custom/)
bash scripts/run_all.sh custom
```

## Eval with your data

Post-fit **eval** still needs BSIM (or PTM) models to build `golden/<pdk>/ref/` waveforms. For fit-only workflows, use `--skip-eval` or omit the eval step.
