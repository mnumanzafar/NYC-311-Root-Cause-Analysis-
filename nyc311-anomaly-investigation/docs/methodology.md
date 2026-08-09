# Methodology

## 1. Detect
- **Rolling bands** — 28-day mean ±2σ to visualize, never to conclude.
- **PELT (ruptures, rbf cost)** — locates breakpoints; penalty tuned so breakpoint count is
  stable across penalties 5-20 (sensitivity noted in the case study).
- **CUSUM** — standardized against an in-control baseline window, slack (drift) 0.5,
  decision threshold 5.0. Confirms a *sustained* shift rather than a spike.
- **Seasonal baseline** — same calendar window in the 3 prior years; report % change and σ.

## 2. Hypothesize
All hypotheses are written down before any confirmatory test, each with the observable
pattern it predicts. This prevents post-hoc storytelling.

## 3. Test
- **STL** (period 7 for weekly, 365 for annual) separates trend from seasonality.
- **Two-proportion z-test** on a segment's share of total volume across periods.
- **Chi-square** on the period × segment contingency table; Cramér's V for effect size.
- **Welch's t / Mann-Whitney** for daily-level mean comparisons without equal-variance
  or normality assumptions.
- **Benjamini-Hochberg** FDR correction across the full battery — with ~20 segments,
  uncorrected α = 0.01 still yields false positives.
- **Isolation Forest + trimmed means** confirm the shift is not a handful of extreme days.

## 4. Conclude
Root cause is stated with: isolation evidence, significance, timing alignment, negative
controls (segments that did *not* move), a confidence level, and explicit falsification criteria.

## 5. Assumptions and threats to validity
- Daily counts are over-dispersed; z-tests are on proportions, not raw counts.
- Multiple comparison risk handled by FDR, not Bonferroni (too conservative here).
- Observational data: timing alignment supports, but does not prove, causation.
