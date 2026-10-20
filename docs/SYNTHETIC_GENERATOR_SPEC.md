# RetailPulse 360 — Independent Synthetic Generator Specification

**Version:** 0.1.0-draft  
**Status:** `PROPOSED — NO GENERATOR CODE IMPLEMENTED`

## 1. Clean-room data generation principles

All IDs, names, amounts, source rhythms, seasonal functions, scenarios and narratives are **invented**. Do not use, perturb, mask, rescale, synthesize from or fit parameters to private employer data, dashboards or distribution summaries. Use a single declared synthetic input specification version plus independent, seed-controlled pseudorandom streams so observed output can be reproduced exactly.

**Core settings (draft):**

| Parameter | Proposed value |
|---|---|
| `generator_version` | `1.0.0` (first implementation target) |
| `base_seed` | `3602026` |
| `observation_start` | `2025-01-01` |
| `observation_end` | `2026-12-31` |
| `store_count` | `30` distinct invented stores |
| `currency_code` | `CUR` (fictional) |
| `official_channels` | `RETAIL`, `PROGRAM` |
| `nonadditive_digital_family` | `MARKETPLACE` attributed within Retail |
| `calendar` | calendar year, Saturday–Friday week |
| `default_output_order` | date, store key, channel/account key, as applicable |
| `scenario_mode` | explicit manifest-driven transformations, never opaque global randomness |

## 2. Store profile and lifecycle proposal

Create 30 synthetic store keys `S001`–`S030` that are solely generated for this project (not recycled from any other project). Geography labels are invented, non-geocoded text without real store addresses. Each store is assigned an independent immutable profile and synthetic open/close history.

| Cohort | Count | Requirement |
|---|---:|---|
| Mature at baseline | 20 | opened before 2025-01-01; includes 2 that will close during 2026 |
| Newly opened during 2025 | 6 | distinct approved opening dates; may reach full-year eligibility only when both comparative windows permit |
| Newly opened during 2026 | 4 | excluded from 2026 Strict when no comparable 2025 period |
| **Distinct total** | **30** | opening/closure labels are **cohorts**, not extra stores |

Two closure events occur within 2026 for stores from the mature cohort; at least one closure should be late enough to yield an earlier Strict comparable period (e.g. August) and a later ineligible partial period (e.g. September). Exact dates, city labels and store assignments are **draft examples** set in the scenario configuration and not company-derived.

## 3. Deterministic factor model (proposal, not code)

The generation algorithm should connect business variables coherently, not draw sales and transactions as unrelated random values:

```text
store_characteristics = invented store_strength × maturity × geography_pattern
expected_transactions = base_demand × store_characteristics × calendar_seasonality
                        × weekday_factor × period_trend × declared_local_shock
actual_transactions  = deterministic seeded count draw around expected_transactions
base_basket_value    = store_basket_profile × seasonal_basket_shift
                        × declared_mix_effect × small local random perturbation
retail_sales         = generated disjoint retail transactions × modeled basket values
program_sales        = generated disjoint program transactions × modeled basket values
returns              = separately generated nonnegative amounts, with rare returns-only days
net_sales            = gross_sales - returns
marketplace_attributed = modeled subset of *Retail*, not a new official revenue stream
```

- Use a **dedicated RNG** for each entity/family/scenario and a documented deterministic key-to-stream strategy. Same seed/config/generator version must produce stable content independent of filesystem traversal or iteration order.
- Fixed per-store strength and profile classes create durable high/medium/low performance; seasonal profiles and bounded growth trends vary over 2025–2026.
- Invented weekly and monthly patterns; a Saturday–Friday week is a reporting standard, **not** a claim about an actual retail business.
- Use seeded transaction counts (e.g., Poisson-like with positive expected count or other tested integer generator) and bounded basket variation. Store-level transaction counts are nonnegative integers.
- Draw channel mix under a governed total without counting a receipt in both channels. Program adoption may differ by store and date.
- For explicit verified-zero days, generate reported zero rows for each expected additive channel; do not use missing-row representation for known zero.
- Return injection: nonnegative return amount, sometimes > gross so **negative net** survives; preserve raw fields and transaction counts. Do not label every negative as corruption.
- Marketplaces adopt by account effective start/end dates; use account mapping to exactly one store on each valid date. Multiple accounts per store permitted.
- Standard baseline digital attribution is nonadditive and internally feasible by construction; deliberate injection may create impossible/out-of-range comparisons as DQ scenarios.

**Do not assume** customer uniqueness or physical visits from generated daily transaction counts. If a future phase needs customer analytics, create a new explicit privacy-safe transaction/customer grain contract before adding any customer metric.

## 4. Reproducible source deliverables

### Official source family

- Daily synthetic source records by store/date/official channel with `gross_sales`, `returns_amount`, `net_sales`, `transactions`, `units` plus source row identity and lineage.
- Separate `snapshot_id`, `source_asof`, coverage expectations, declared schema version and canonical content fingerprint.
- Raw snapshots must be immutable after creation; later scenarios generate new snapshot versions, not mutate a committed baseline silently.

### Marketplace family

- Per-account/date digital amounts, orders, units and account-mapping effective history with independent `source_asof`; correct nonadditive semantics.
- Preserve digital records past Official As-Of, if present, for a source-freshness mismatch scenario.

### Budget source

- Distinct monthly target by store/month/channel; independent store/channel performance factors. Monthly target covers the **calendar month**, not days open or days elapsed.
- Store lifecycle applies only to effective daily allocation, not by dropping monthly budget master inputs.

### Provenance and scenario manifest

Track `generator_version`, `seed`, declared scenario, parameter hash, ordered source file list and SHA256, source As-Of for each family, row counts, key counts, amount totals, explicit scenario change ledger and expected DQ alerts. Stable canonical data excludes volatile run timestamp metadata.

## 5. Scenario matrix: required observable changes

| Scenario ID | Controlled transformation | Expected result / assertion |
|---|---|---|
| `GEN-BASE` | initial reproducible baseline, store opens/closes, seasonality, valid zero/negative days | 30 distinct stores; correct financial and source arithmetic; known fixture expectations |
| `SNAP-ADD` | add one previously nonexistent unprotected Official/digital business key in a new full snapshot | one new published key, correct totals; no duplicate |
| `SNAP-CORRECT` | replace one unprotected existing amount at exact same business key | old value replaced; no double count; ledger records delta |
| `SNAP-RETRACT` | remove one unprotected key from a later *complete* full snapshot | key removed, no previous-output resurrection; include explicit confirmed-retraction coverage/ledger evidence, not zero replacement |
| `SNAP-EARLIER-ASOF` | replace present snapshot with independently valid earlier As-Of | only rows <= earlier As-Of plus eligible protected archive rows, correct ledger and source-freshness status |
| `SNAP-ARCHIVE-RESTORE` | omit protected closed-store record from current source, preserve archived key | restores protected historical row with archive fingerprint intact |
| `SNAP-ARCHIVE-CONFLICT` | present archived protected key with modified canonical values | `BLOCKED`, previous generation untouched |
| `SNAP-ARCHIVE-HASH` | corrupt protected manifest/content hash | `BLOCKED` before publish |
| `SNAP-DUPLICATE-KEY` | inject duplicate source business key | `BLOCKED`, never silent deduplicate |
| `SNAP-UNKNOWN-STORE` | unknown/invalid store key | `BLOCKED` or explicit quarantine policy depending severity contract |
| `SNAP-MISSING-COVERAGE` | omit expected active reported row without declaring valid zero | unexpected missing coverage finding, not replaced with 0; required baseline completeness gate fails (unlike independently confirmed retraction) |
| `SNAP-NEGATIVE-VALID` | valid returns exceed gross on selected days | negative net passes expected-business-case QA |
| `SNAP-ZERO-VALID` | exactly zero transactions and sales on active eligible store/day | budget applies; LFL coverage remains eligible |
| `SNAP-DIGITAL-AHEAD` | marketplace As-Of later than Official | digital data retained; ratio matched only through min As-Of |
| `SNAP-DIGITAL-MISMATCH` | inject digital amount > aligned Retail or broken account mapping | DQ finding with impacted keys; do not double-count or suppress |
| `SNAP-PUBLISH-FAIL` | interrupt staged publish before pointer swap | previous generation manifest/pointer and hash remain unchanged |
| `SNAP-IDEMPOTENT` | repeat identical inputs/config/archive | same canonical content hashes and totals; no record accumulation |

**Scenario ledger minimum fields:** `scenario_id`, `family`, `business_key`, `change_type`, `before_value_hash`, `after_value_hash`, `expected_qa_check`, `expected_publish_status`.

## 6. Generator acceptance and feasibility checks

1. Exactly 30 distinct store business keys and correct cohort counts; dates constrained by declared observation and store lifecycle.
2. All source keys unique at their declared grains, schema complete, no unexplained broken FK or missing account ownership.
3. `gross >=0`, `returns >=0`, `net=gross-returns`, nonnegative integer transaction counts. Realistic relationship of transactions to sales/basket except explicitly declared valid return/zero edge cases.
4. Source coverage explicitly lists reported/zero/missing/not-applicable states; no missing-to-zero coercion.
5. Marketplace normally attributed only within Retail; no additive impact on official totals; fault cases detectable.
6. Source same seed + same version + parameters → byte-identical canonical input fixtures and manifest content hashes; different version/seed fingerprint must be traceable.
7. Snapshot scenario changes occur at known keys and are completely enumerated in ledger; as-of rollbacks and protected conflicts behave as documented.
8. Seasonal and across-store variation is **synthetically plausible**, but not calibrated to or described as any real retail population.
9. No PII, genuine company codes, real addresses, proprietary data or template-derived report metrics.
10. Baseline may include generated dates later than the user's actual present date because it is a **simulated 2025–2026 universe**; such records must never be presented as observed current reality.

## 7. No implementation assertion

This specification is Phase 1 planning only. There are no generator output hashes, actual row counts, generated snapshots or passing tests until Phase 2 executes and produces independent evidence.
