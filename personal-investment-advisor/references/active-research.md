# Active research workflow

PIA treats faster return-seeking as an evidence and allocation research problem, not as an execution mandate. The active path is offline and fail-closed:

1. `alpha-validate` checks a point-in-time evidence package and promotion policy. It measures out-of-sample, cost-adjusted information ratio, stressed costs, drawdown, turnover, an approximate deflated-Sharpe probability, and a CSCV-style probability of backtest overfitting.
2. `alpha-scan` accepts only a package whose validation report is `eligible_for_active_research`. It applies confidence and evidence-age decay, uncertainty haircuts, and produces Rank/Yank research pools.
3. `portfolio-construct` computes an equal-risk-contribution benchmark from the full supplied covariance matrix, then a bounded robust-alpha candidate under transaction-cost, turnover, and per-name change constraints.
4. `rebalance-proposal` compares current and candidate allocations over an explicit review horizon and no-trade band.

## Non-negotiable boundary

- Every artifact is `research_only`, read-only, and non-executable.
- Candidate weights and allocation gaps are permitted only after the P0 validation gate passes. They must be labelled `candidate_weight` or `allocation_gap`; never `target_weight`.
- No command may place, schedule, route, or simulate an order; infer missing holdings; fetch mutable live data; or overwrite an input.
- A failed contract, stale component, unbound upstream hash, non-PSD covariance matrix, infeasible constraint set, or optimizer non-convergence fails closed.
- Expected alpha, covariance, costs, and horizons are assumptions. Passing a statistical gate does not establish future profitability.

## Input contracts

- Alpha package: `references/alpha_evidence_schema.json`
- Promotion policy: `references/alpha_promotion_policy_schema.json`
- Scan policy: `references/active_scan_policy_schema.json`
- Construction policy: `references/active_construction_policy_schema.json`
- Proposal policy: `references/rebalance_proposal_policy_schema.json`

All datetimes must be timezone-aware. Source evidence must use a non-test public or `dataset://` locator and a lowercase SHA-256. The package must explicitly attest point-in-time availability, survivorship-bias control, and corporate-action adjustment.

## Interpretation

`eligible_for_active_research` means that the submitted experiment cleared the supplied promotion thresholds. It does not mean approved for capital deployment. Rank/Yank is an attention-allocation device; the Yank pool is a review list, not a sell list. The final proposal becomes actionable only through a separate human governance and execution process outside this skill.
