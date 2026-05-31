Extract query requirements and atomic factual claims for claim-centered evaluation.

Query:
{query}

Report sections JSON:
{sections_json}

Return a JSON object with this shape:
```json
{{
  "requirements": [
    {{"id": "r1", "text": "requirement text", "importance": "high|medium|low"}}
  ],
  "claims": [
    {{
      "id": "c1",
      "text": "atomic factual claim",
      "section_id": "s1",
      "importance": "high|medium|low",
      "citation_ids": ["1"],
      "requirement_ids": ["r1"]
    }}
  ]
}}
```

Extract at most {max_claims} claims. Omit empty or non-factual claims.
