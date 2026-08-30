# Publishing acm-fit (LASCAS open release)

This directory is a self-contained snapshot for public release as **`acm-fit`**.

## Pre-publish checklist

- [x] `bash scripts/run_smoke.sh` passes
- [x] `config/pdk_env.local.json` is **not** committed (gitignored)
- [ ] `results/*/` regenerated or subset frozen for paper (optional; large dirs gitignored)
- [ ] Update `CITATION.cff` `repository-code` URL after remote is created
- [ ] Tag `v0.1.0-lascas-2026`

## Initial publish (new repo)

```bash
cd publications/release/lascas

# Verify smoke test
bash scripts/run_smoke.sh

# Initialize and commit (from this directory only)
git add -A
git status   # confirm no pdk_env.local.json, no vendor clone, no full results/
git commit -m "Release acm-fit v0.1.0 for LASCAS 2026"

# Create remote (Cursor origin CLI or GitHub) and push
git remote add origin <clone-url>
git push -u origin main
git tag v0.1.0-lascas-2026
git push origin v0.1.0-lascas-2026
```

## What ships in the repo

| Path | Purpose |
|------|---------|
| `src/` | Python pipeline (sync from monorepo via `scripts/sync_src.sh`) |
| `models/acm5/` | UFSC ACM-5 VA + prebuilt OSDI |
| `config/` | Golden/eval suites, tier registry, `pdk_env.example.json` |
| `scripts/` | `run_all.sh`, smoke, plot, corner report |
| `figures/` | Paper figures (PNG) |
| `.github/workflows/smoke.yml` | CI |

## What stays out of git

- Foundry PDK model files (`SKY130_LIB`, `GF180_MODELS_DIR`)
- `vendor/spice_model_collections/` (clone per README)
- `config/pdk_env.local.json`
- `work/` (OpenVAF download cache)
- Full `results/` trees (regenerate locally)

## Paper artifacts

Manuscript LaTeX: `publications/writing/lascas/` — `make pdf` builds `lascas.pdf`.
