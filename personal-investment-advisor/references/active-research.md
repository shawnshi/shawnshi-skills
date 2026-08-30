# Active research workflow

PIA treats faster return-seeking as an evidence and allocation research problem, not as an execution mandate. The active path is offline and fail-closed:

1. `alpha-validate` checks a point-in-time evidence package and promotion policy. It measures out-of-sample, cost-adjusted information ratio, stressed costs, drawdown, turnover, an approximate deflated-Sharpe probability, and a CSCV-style probability of backtest overfitting.
2. `alpha-scan` accepts only a package whose validation report is `eligible_for_active_research`. It applies confidence and evidence-age decay, uncertainty haircuts, and produces Rank/Yank research pools.
3. `portfolio-construct` computes an equal-risk-contribution benchmark from the full supplied covariance matrix, then a bounded robust-alpha candidate under transaction-cost, turnover, and per-name change constraints.
4. `rebalance-proposal` compares current and candidate allocations over an explicit review horizon and no-trade band.

## Personal-investor free-data mode

The default acquisition layer uses free public sources: SEC EDGAR `companyfacts` and filings for US point-in-time fundamentals, exchange/issuer/CNInfo disclosures for A/H shares, Yahoo Finance or Akshare for best-effort market history, and a public broker fee schedule for costs. Paid terminals, licensed academic databases, and sell-side consensus feeds are never assumed.

A free-source package may honestly set `survivorship_bias_control=false` or `corporate_action_adjusted=false`. These booleans are valid inputs, so `alpha-validate` still computes the available experimental metrics; each false value is a failed promotion check and prevents `eligible_for_active_research`. It must not be changed to true merely to satisfy the gate.

SEC EDGAR solves filing availability for US fundamentals but does not itself supply historical index membership or delisting returns. Current constituents therefore remain survivorship-biased unless public historical membership and delisted total returns are independently bound. When promotion is blocked, risk-only `experimental_weight` analysis may still use the separate inverse-volatility workflow; it is not Rank/Yank or an active-alpha candidate.

## Non-negotiable boundary

- Every artifact is `research_only`, read-only, and non-executable.
- Candidate weights and allocation gaps are permitted only after the P0 validation gate passes. They must be labelled `candidate_weight` or `allocation_gap`; never `target_weight`.
- No active-research calculation command may place, schedule, route, or simulate an order; infer missing holdings; fetch mutable live data; or overwrite an input. Free-source acquisition occurs beforehand through a separate evidence command and its immutable output hash is then bound offline.
- A failed contract, stale component, unbound upstream hash, non-PSD covariance matrix, infeasible constraint set, or optimizer non-convergence fails closed.
- Expected alpha, covariance, costs, and horizons are assumptions. Passing a statistical gate does not establish future profitability.

## Input contracts

- Alpha package: `references/alpha_evidence_schema.json`
- Promotion policy: `references/alpha_promotion_policy_schema.json`
- Scan policy: `references/active_scan_policy_schema.json`
- Construction policy: `references/active_construction_policy_schema.json`
- Proposal policy: `references/rebalance_proposal_policy_schema.json`

All datetimes must be timezone-aware. Source evidence must use a non-test public, `sec://`, or user-controlled `dataset://` locator and a lowercase SHA-256. The package must explicitly report point-in-time evidence and boolean survivorship/corporate-action states. `false` means experimental evidence, not malformed input; both values must be `true` before promotion.

## Interpretation

`eligible_for_active_research` means that the submitted experiment cleared the supplied promotion thresholds. It does not mean approved for capital deployment. Rank/Yank is an attention-allocation device; the Yank pool is a review list, not a sell list. The final proposal becomes actionable only through a separate human governance and execution process outside this skill.
