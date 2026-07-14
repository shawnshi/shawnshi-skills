# Collaboration Audit Evidence Schema

Use this schema only when the user requests a structured JSON artifact.

```json
{
  "schema_version": 1,
  "scope": {
    "period": "7d",
    "sources": [],
    "missing_data": []
  },
  "metrics": [
    {
      "name": "rework_events",
      "value": 0,
      "unit": "count",
      "method": "documented calculation"
    }
  ],
  "findings": [
    {
      "id": "F-001",
      "claim": "Concise evidence-backed finding",
      "evidence": [],
      "confidence": "low|medium|high",
      "alternatives": [],
      "impact": "Observed operational impact"
    }
  ],
  "recommendations": [
    {
      "finding_id": "F-001",
      "action": "Bounded recommendation",
      "owner": null,
      "verification": "How to verify the result"
    }
  ],
  "residual_risks": []
}
```

Rules:

- Do not include private content outside the authorized scope.
- Do not label inference as observation.
- Keep evidence references resolvable from the delivered artifact.
- Save only to the user-specified location.
