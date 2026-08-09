# Why did Brooklyn 311 complaint volume drop in Q3 2023?

> **Status: template.** Replace every `<...>` placeholder with results from the notebooks.
> This document — not the notebooks — is the deliverable.

## 1. Executive Summary
Brooklyn 311 complaint volume fell **<X>%** in Q3 2023 versus the 3-year seasonal
baseline (**<-N.N>σ**). The decline is isolated to **<segment>**, not city-wide, and its
onset matches **<event/date>**. Recommendation: **<one action>**.

## 2. The Anomaly
- Metric: daily 311 service requests, Brooklyn.
- Detection: PELT change-point at **<date>** (penalty <p>), confirmed by CUSUM alarm on <date>.
- Magnitude: mean daily volume <before> -> <after> (**<X>%**).
- Seasonal check: <-N.N>σ vs. the same calendar window in <k> prior years.

![Volume with ±2σ bands](figures/01_volume_bands.png)
![Change points](figures/02_changepoints.png)

## 3. Hypotheses Considered
| # | Hypothesis | Prediction if true |
|---|---|---|
| H1 | Seasonality artifact / wrong baseline | Drop disappears after STL de-seasonalizing |
| H2 | Data collection change | A category stops appearing entirely at a clean boundary |
| H3 | Real behavioral decline | Gradual decline, mirrored in related outcome metrics |
| H4 | External shock (weather, holidays, staffing) | Drop correlates with the shock window and reverts |
| H5 | Reporting-channel change | All complaint types drop roughly equally |
| H6 | Policy change routing a category elsewhere | Drop isolated to one category, sharp onset at rollout date |

## 4. Investigation
### H1 — Seasonality
Test: STL decomposition (period 7 and 365) + seasonal-baseline σ. Result: **<result>**.
### H2 — Data collection change
Test: category continuity, distinct-value counts per month, null-rate shifts. Result: **<result>**.
### H3 — Real behavioral decline
Test: trend component slope, related metrics (resolution times, repeat callers). Result: **<result>**.
### H4 — External shock
Test: join `data/external/` weather + holiday calendar, regression with controls. Result: **<result>**.
### H5 — Reporting channel
Test: cohort by `channel`, chi-square on channel mix across periods. Result: **<result>**.
### H6 — Policy change
Test: cohort by `complaint_type`, two-proportion z-test on category share, timing alignment. Result: **<result>**.

![Cohort breakdown](figures/04_cohort.png)

## 5. Root Cause & Evidence
**Root cause: <statement>.** Evidence:
(a) drop isolated to <category> (<contribution>% of total change);
(b) statistically significant at p < 0.01 (<test>, statistic <s>);
(c) onset within <n> days of <event>;
(d) all other categories flat in the same window (|pct change| < <t>%);
(e) survives trimming the 5 most extreme days each side (Isolation Forest cross-check).

**Confidence: <high/medium/low>.** **Falsification:** this conclusion would be overturned by
<counter-evidence>. **Next check with more data:** <next step>.

## 6. Confounders Ruled Out
| Hypothesis | Test | Result | Verdict |
|---|---|---|---|
| Seasonality | STL + seasonal σ | <p / σ> | Ruled out |
| Data collection change | Category continuity | <result> | Ruled out |
| External shock | Weather/holiday controls | <result> | Ruled out |
| Channel migration | Chi-square on channel mix | <p> | Ruled out |
| Extreme-day artifact | Isolation Forest + trimmed mean | <result> | Ruled out |

## 7. Business Recommendation
1. **<Action>** — owner <team>, because <evidence link>.
2. **Instrument it** — add a monitor: alert when a category's weekly share moves >Nσ.
3. **Expected impact** — <quantified estimate + how you would measure it>.

## 8. Appendix — Methodology & Limitations
- Methods: PELT change-point, CUSUM, STL, two-proportion z-test, chi-square (Cramér's V),
  Benjamini-Hochberg FDR control, Isolation Forest.
- Limitations: 311 records reports, not incidents; borough field has nulls; category taxonomy
  changed in <year>; observational data — associations, not proven causation.
- Reproducibility: `make setup && make etl && make test`; all stats logic in `src/analysis/` with pytest coverage.
