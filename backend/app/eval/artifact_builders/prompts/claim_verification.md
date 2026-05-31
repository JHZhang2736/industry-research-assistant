Verify whether each claim is supported by the provided evidence.

Claims JSON:
{claims_json}

Evidence JSON:
{evidence_json}

Return a JSON object with this shape:
```json
{{
  "verdicts": [
    {{
      "claim_id": "c1",
      "supported": true,
      "reason": "brief reason",
      "evidence_ids": ["f1"],
      "confidence": "high|medium|low"
    }}
  ]
}}
```

Include one verdict for every claim when possible.
