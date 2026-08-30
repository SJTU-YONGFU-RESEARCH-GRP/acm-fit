# Benchmark snapshot (paper artifacts)

Frozen summary from `results/commercial/` and `results/ptm/` runs (2026-08-30).
Regenerate full trees with `bash scripts/run_all.sh commercial` and `bash scripts/run_all.sh ptm`.

## Commercial corners — ACM-5 DC weighted error

| Target | Weighted err | VT0 (mV) | IS (nA) | n | ζ |
|--------|-------------:|---------:|--------:|--:|--:|
| sky130_tt | 0.177 | 817 | 3387 | 1.76 | 0.051 |
| sky130_ss | 0.256 | 688 | 520 | 1.43 | 0.022 |
| sky130_ff | 0.202 | 802 | 4638 | 1.87 | 0.021 |
| gf180mcu_typical | 0.280 | 839 | 2747 | 2.24 | 0.008 |
| gf180mcu_ss | 0.159 | 793 | 991 | 1.45 | 0.036 |
| gf180mcu_ff | 0.254 | 633 | 1286 | 2.12 | 0.008 |

Full corner report: `results/commercial/CORNER_REPORT.md` (after commercial run).

## PTM scaling — ACM-5 DC weighted error

| Node | 180 nm | 130 nm | 90 nm | 65 nm | 45 nm | 32 nm | 22 nm |
|------|-------:|-------:|------:|------:|------:|------:|------:|
| Err. | 0.166 | 0.144 | 0.134 | 0.151 | 0.135 | 0.140 | 0.193 |

## Eval (typical corners, ACM vs BSIM golden)

| PDK | Analysis | Metric |
|-----|----------|--------|
| sky130_tt | DC | Id RMSE log 0.359 |
| sky130_tt | AC | Vmag RMSE 0.274 |
| sky130_tt | temp | Id RMSE log 0.192 |
| gf180mcu_typical | DC | Id RMSE log 0.439 |
| gf180mcu_typical | AC | Vmag RMSE 0.391 |

Run: `bash scripts/run_all.sh commercial --eval`

## Figures

```bash
python3 scripts/plot_paper_figures.py   # → figures/*.png
```

Paper LaTeX: `publications/writing/lascas/` — `make pdf`
