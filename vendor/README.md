# Vendor dependencies

## spice_model_collections (PTM lane)

Clone the PTM BSIM corpus for the `ptm` benchmark lane:

```bash
git clone https://github.com/SJTU-YONGFU-RESEARCH-GRP/spice_model_collections.git \
  vendor/spice_model_collections
```

Set `SMC_ROOT=vendor/spice_model_collections` in `config/pdk_env.local.json`.

## Commercial PDKs (not redistributed)

sky130 and GF180MCU model files are **not** bundled. Install the open PDKs locally
and point `SKY130_LIB` and `GF180_MODELS_DIR` in `config/pdk_env.local.json`.
