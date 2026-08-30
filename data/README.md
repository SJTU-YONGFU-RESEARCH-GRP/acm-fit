# Frozen golden dataset (BSIM reference I–V)

Pre-captured **Id–Vg** reference curves used as fit targets. Lets you run
fit → predict → eval **without** a foundry PDK install or live BSIM capture.

## Layout

```text
data/golden/
├── commercial/          # sky130 + gf180mcu corners (6 targets)
│   └── <target>/
│       ├── meta.json
│       └── idvg_vds_*.csv
└── ptm/                 # PTM 180 nm–22 nm (7 nodes)
    └── <node>/
        ├── meta.json
        └── idvg_vds_*.csv
```

| Lane | Targets | Source |
|------|---------|--------|
| `commercial` | `sky130_{tt,ss,ff}`, `gf180mcu_{typical,ss,ff}` | ngspice + open PDK BSIM |
| `ptm` | `ptm180` … `ptm22` | ngspice + [spice_model_collections](https://github.com/SJTU-YONGFU-RESEARCH-GRP/spice_model_collections) PTM cards |

Each `meta.json` records device geometry, VDD, sweep settings, and corner metadata.

## Use frozen goldens

```bash
# Import into results/ then fit (skip live BSIM capture)
bash scripts/import_golden_data.sh commercial
bash scripts/run_all.sh commercial --skip-golden

# Or one step
bash scripts/run_all.sh commercial --frozen-golden
```

PTM lane:

```bash
bash scripts/run_all.sh ptm --frozen-golden
```

Eval still needs PDK paths (`SKY130_LIB`, `GF180_MODELS_DIR`) or `SMC_ROOT` for
live BSIM reference waveforms under `results/<lane>/golden/<pdk>/ref/`.

## Regenerate

```bash
bash scripts/run_all.sh commercial          # overwrites results/commercial/golden/
bash scripts/export_golden_data.sh commercial # refresh data/golden/commercial/
```

`export_golden_data.sh` copies `*.csv` and `meta.json` from `results/<lane>/golden/`.
