# ACM-5

Baseline design-oriented ACM compact MOSFET model with **5 DC parameters**: `{VT0, IS, n, sigma, zeta}`.

| Item | Path |
|------|------|
| Verilog-A (NMOS) | `models/acm5/NMOS_ACM_2V0.va` |
| Verilog-A (PMOS) | `models/acm5/PMOS_ACM_2V0.va` |
| Module | `nmos_ACM` / `pmos_ACM` |
| OSDI | `models/acm5/NMOS_ACM_2V0.osdi` |

Upstream UFSC sources live in `ACM-MOSFET-models/` (gitignored submodule) for refresh; the registry uses the vendor copy under `models/acm5/`.

ACM-5 is an **independent charge-based compact model** (ACM / UCCM from the UFSC Galup-Montoro–Schneider lineage), not an algebraic simplification of BSIM. BSIM/PDK models are the **reference** used for validation and extraction targets.

The design core adds one high-field parameter (`zeta`) on top of the ACM-4 set. As \(\zeta\to 0\), ACM-5 recovers ACM-4. The VA also provides analytic \(g_m\), charge/C–V, temperature, mismatch, and noise outside the 5-DC core.

---

## Physical picture

Same charge-based foundation as ACM-4: gate control is expressed through a **pinch-off voltage** \(V_P\), converted to **normalized inversion charges** \(q_S\) and \(q_D\) via UCCM, then to current via an ACM \(i_f-i_r\) law.

ACM-5 extends that picture for **short channels / high lateral fields**, where carriers can approach a saturation velocity \(v_{\mathrm{sat}}\) before the classical geometrical pinch-off (\(q_D=0\)) is reached.

### Long-channel vs high-field saturation

| Regime | Limiting mechanism | ACM description |
|--------|--------------------|-----------------|
| Long \(L\), moderate \(E_y\) | Drain-end charge → 0 (pinch-off) | \(q_D\to 0\); \(I_D\to I_S q_S(q_S+2)\) (ACM-4) |
| Short \(L\), large \(E_y\) | Drift velocity → \(v_{\mathrm{sat}}\) | Residual drain charge \(q_{\mathrm{sat}}>0\); current soft-limited by \(\zeta\) |

Velocity saturation means the drain end of the channel still holds some inversion charge, but that charge no longer increases current proportionally—extra lateral field goes into heating / scattering rather than higher drift speed. ACM-5 captures this with \(\zeta\) and \(q_{\mathrm{sat}}(\zeta)\).

---

## Design parameters — physical roles

| Param | Units | Physical role | What it mainly shapes |
|-------|-------|---------------|------------------------|
| `VT0` | V | Threshold (zero-bias) | Shift of \(I_D\)–\(V_G\); strong-inversion onset |
| `IS` | A | Specific current / \(\mu C_{\mathrm{ox}}W/L\) scale | Absolute \(I_D\); moderate-inversion corner |
| `n` | — | Slope factor \(\approx 1+C_{\mathrm{dep}}/C_{\mathrm{ox}}\) | Weak-inversion log slope; body effect |
| `sigma` | — | Compact DIBL / barrier lowering | Multi-\(V_{DS}\) threshold shift / barrier |
| `zeta` | — | Velocity saturation / high lateral field | Saturation current ceiling & SI sat shape on short \(L\) |

Also in the VA: geometry, junction/overlap C–V, temperature (`alpha*`), mismatch (`aVT0`,`aK`), noise (`N_ot`).

---

## Core DC equations

Thermal voltage \(\phi_t=kT/q\). Temperature-adjusted symbols: `VT0_T`, `IS_T`, `sigma_T`, `zeta_T`.

### 1. Pinch-off voltage \(V_P\)

\[
V_P = \frac{V_{GB}-V_{T0}+\sigma(V_{DB}+V_{SB})}{n}
\]

**Physics.** Same as ACM-4: \(V_P\) is the channel potential at which inversion would vanish for the present gate bias. \(n\) accounts for the capacitive divider between oxide and depletion layers (body effect). \(\sigma\) is a compact DIBL term—drain/source fields lower the source-end barrier, increasing inversion at fixed \(V_G\). Without \(\sigma\), multi-\(V_{DS}\) families disagree with short-channel BSIM even if \(V_T\) at one bias is perfect.

### 2. Source-end charge \(q_1\) (UCCM)

With \(V_{XB}=\min(V_{SB},V_{DB})\):

\[
X = \exp\!\left(\frac{V_P-V_{XB}}{\phi_t}+1\right),
\quad
q_1 = \mathcal{A}_{443}(X)
\]

**Physics.** UCCM links gate overdrive to mobile charge through a single continuous relation (weak → moderate → strong inversion). Algorithm 443 approximates the required Lambert-\(W\)-like inversion. Large \(q_1\): strong inversion at the more inverted end; small \(q_1\): subthreshold.

### 3. Saturation charge \(q_{\mathrm{sat}}(\zeta)\) — velocity-sat ceiling

\[
q_{\mathrm{sat}}
=
q_1 + 1 + \frac{1}{\zeta}
-
\sqrt{\left(1+\frac{1}{\zeta}\right)^2+\frac{2q_1}{\zeta}}
\]

**Physics.** In the gradual-channel picture with a finite \(v_{\mathrm{sat}}\), current cannot grow without bound as the drain end is “emptied.” Mathematically this appears as a **floor** on the usable drain charge: the effective reverse charge cannot fall below \(q_{\mathrm{sat}}\). Properties:

- \(\zeta\to 0\) (no velocity sat) \(\Rightarrow\) \(q_{\mathrm{sat}}\to 0\) (ACM-4 limit)
- Larger \(\zeta\) (stronger high-field effect / shorter effective \(L\)) \(\Rightarrow\) larger \(q_{\mathrm{sat}}\) \(\Rightarrow\) earlier, softer saturation

Related process view in the VA:

\[
\mu \propto \frac{I_S L}{C_{\mathrm{ox}}\,n\,\phi_t^2 W},
\qquad
v_{\mathrm{sat}} = \frac{\mu\,\phi_t}{L\,\zeta}
\]

so \(\zeta \sim \mu\phi_t/(L v_{\mathrm{sat}})\): dimensionless measure of how hard the device hits velocity saturation for its length and mobility.

### 4. Drain-end charge \(q_2\)

With \(V_{YB}=\max(V_{DS},V_{SD})\):

\[
Y = (q_1-q_{\mathrm{sat}})\,\exp\!\left(-\frac{V_{YB}}{\phi_t}\right)\exp(q_1-q_{\mathrm{sat}}),
\quad
q_2 = \mathcal{A}_{443}(Y) + q_{\mathrm{sat}}
\]

Then \(q_S,q_D\) are assigned from \(q_1,q_2\) with source–drain symmetry (swap if \(V_{DS}<0\)).

**Physics.** The drain end sees a reduced effective forward charge \((q_1-q_{\mathrm{sat}})\) and an exponential drop with reverse bias \(V_{YB}\), then \(q_{\mathrm{sat}}\) is added back so the drain charge never falls below the velocity-sat floor. That is the compact expression of “pinch-off modified by \(v_{\mathrm{sat}}\).”

### 5. Drain current

\[
I_D = m\,I_S\cdot
\frac{(q_S+q_D+2)\,(q_S-q_D)}
{1+\sqrt{\zeta^2(q_S-q_D)^2+\varepsilon^2}}
\]

(\(\varepsilon\) is a small symmetry regularizer so \(V_{DS}\leftrightarrow V_{SD}\) stays smooth at the origin.)

**Physics — numerator.** Same long-channel ACM structure as ACM-4:

\[
i_f-i_r = (q_S-q_D)(q_S+q_D+2)
\]

combines diffusion-like (\(\propto q_S-q_D\)) and drift-like (\(\propto q_S^2-q_D^2\)) contributions in one formula.

**Physics — denominator.** The factor

\[
1+\sqrt{\zeta^2(q_S-q_D)^2+\varepsilon^2}
\]

reduces current when \(|q_S-q_D|\) is large **and** \(\zeta>0\): that is exactly when the lateral field (charge gradient along the channel) is high enough for velocity saturation to matter. Limits:

| Limit | Behavior |
|-------|----------|
| \(\zeta\to 0\) | Denominator \(\to 1+|\varepsilon|\) → ACM-4 |
| Small \(q_S-q_D\) (linear region) | Little vsat correction |
| Large \(q_S-q_D\) (deep sat, short \(L\)) | Current compressed toward a vsat-limited plateau |

An associated bias quantity used in \(g_m\) / charge formulas is \(q_{I,\mathrm{sat}}=(\zeta/2)\,i_d\), the velocity-sat correction to inversion charge used in the dynamic model.

---

## Plots and analysis

Figures use the same charge/current core as the upstream ACM2 Verilog-A (demo card). Pre-built outputs live in [`figs/`](figs/). ACM-4 companion plots: [`../acm4/ACM4.md`](../acm4/ACM4.md).

### Velocity sat flattens \(I_{D\mathrm{sat}}\)

![ACM-5 zeta Id–Vds](figs/zeta_id_vds.svg)

**What to see.** At fixed \(V_{GS}\), increasing \(\zeta\) leaves the linear region almost unchanged but **lowers and softens** the saturation plateau. \(\zeta\to 0\) recovers the ACM-4 curve.

**Why it matters.** Short-channel BSIM devices often need exactly this DOF: SI saturation current is limited by \(v_{\mathrm{sat}}\), not only by pinch-off. Fit `zeta` last, after `IS` is anchored in moderate inversion / linear region, or the two will trade off (see below).

### Charge floor \(q_{\mathrm{sat}}(\zeta)\)

![ACM-5 qsat vs zeta](figs/qsat_vs_zeta.svg)

**What to see.** For a fixed source-end charge \(q_1\), \(q_{\mathrm{sat}}\) rises with \(\zeta\). Stronger high-field effect → higher residual drain charge allowed at “saturation.”

**Why it matters.** Classical long-channel theory wants \(q_D\to 0\). Velocity saturation forbids that: carriers are already at \(v_{\mathrm{sat}}\) while some inversion charge remains. The closed-form \(q_{\mathrm{sat}}\) is that floor.

### \(q_D\) vs \(V_{DS}\): ACM-4 vs ACM-5

![ACM-5 qd vs Vds with zeta](figs/qd_vs_vds_zeta.svg)

**What to see.** Blue (\(\zeta=0\)): \(q_D\) falls toward zero (pinch-off). Red (\(\zeta>0\)): \(q_D\) asymptotes to \(q_{\mathrm{sat}}\) (dotted purple) instead of emptying.

**Why it matters.** This is the geometric picture behind the current formula’s denominator. Once \(q_D\) is stuck near \(q_{\mathrm{sat}}\), further \(V_{DS}\) mainly drops across a high-field region and does not keep raising \(I_D\).

### Extraction correlation: \(I_S\) ↔ \(\zeta\)

![ACM-5 IS–zeta tradeoff](figs/is_zeta_tradeoff.svg)

**What to see.** Families of \(I_{D\mathrm{sat}}(\zeta)\) for different \(I_S\). A horizontal cut (fixed \(I_{D\mathrm{sat}}\)) can be hit by **high \(I_S\) + high \(\zeta\)** or **lower \(I_S\) + lower \(\zeta\)**.

**Why it matters.** Automated fits can wander along this valley. Practical recipe: lock `IS` from moderate inversion / low-\(V_{DS}\) SI, then fit `zeta` on short-\(L\) saturation shape; only then do a joint refine with tight bounds. The same caution applies to `sigma` ↔ `zeta` on multi-\(V_{DS}\) families.

---

## vs BSIM

| Question | Answer |
|----------|--------|
| Simplified BSIM card? | No — separate ACM/UCCM physics |
| Why compare to BSIM? | Foundry accuracy target for fitting |
| What is simplified? | Design interface: 5 meaningful DC params, single-piece I–V |

Watch extraction correlations on short devices:

| Pair | Why they trade off |
|------|--------------------|
| `IS` ↔ `zeta` | Both scale strong-inversion current; vsat can look like lower effective \(\mu\)/`IS` |
| `VT0` ↔ `n` | Weak-inversion line: slope vs intercept |
| `sigma` ↔ `zeta` | Both affect saturation / \(V_{DS}\) families; DIBL vs high-field compression |

---

## I–V extraction

1. Weak inversion → `n`, `VT0`
2. Specific current / moderate inversion → `IS`
3. Multi-\(V_{DS}\) or \(L\)-sweep → `sigma`
4. Short-\(L\) / high-field saturation shape → `zeta`
5. Optional global refine vs full BSIM curves

Do **not** set `zeta=0` in the upstream ACM2 VA: `vsat`/`qsat` divide by `zeta_T` and the operating point fails. Use ACM-4 (or a tiny positive `zeta`) for the long-channel limit. This repo’s fitter keeps `zeta` in a strictly positive window.

---

## Local fit notes

Early automated fits in this repo: on GF180MCU, ACM-5 beat ACM-4 (free `zeta` matters).  
On SKY130, geometry DOF can matter more than `zeta` alone — treat as extraction correlation, not a free-`W` model parameter.

---

## Family

- ACM-4 (no `zeta`, \(q_{\mathrm{sat}}=0\)): [`../acm4/ACM4.md`](../acm4/ACM4.md)

---

## Benchmark

See [`results/acm5/REPORT.md`](../../results/acm5/REPORT.md) and [`results/SUMMARY.md`](../../results/SUMMARY.md).

See also: [`../acm4/ACM4.md`](../acm4/ACM4.md), [`../acm4c/ACM4c.md`](../acm4c/ACM4c.md).

```bash
bash scripts/run_golden_pipeline.sh --iterations 1000 --jobs 4
```
