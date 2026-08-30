# Vendor dependencies

## spice_model_collections (git submodule)

PTM BSIM model cards for the `ptm` benchmark lane are vendored as a **git submodule**
at `vendor/spice_model_collections`.

**After cloning acm-fit:**

```bash
git submodule update --init --recursive
```

Or clone with submodules in one step:

```bash
git clone --recurse-submodules https://github.com/SJTU-YONGFU-RESEARCH-GRP/acm-fit.git
```

Set `SMC_ROOT=vendor/spice_model_collections` in `config/pdk_env.local.json`
(see `config/pdk_env.example.json`).

**Update the submodule** to the latest upstream commit:

```bash
git submodule update --remote vendor/spice_model_collections
```

Upstream: https://github.com/SJTU-YONGFU-RESEARCH-GRP/spice_model_collections

## Commercial PDKs (not redistributed)

sky130 and GF180MCU model files are **not** bundled. Install the open PDKs locally
and point `SKY130_LIB` and `GF180_MODELS_DIR` in `config/pdk_env.local.json`.
