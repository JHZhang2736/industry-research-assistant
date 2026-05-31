Evaluate the overall quality of this industry research report for the user query:

{query}

Report sections JSON:
{sections_json}

Claim support summary JSON:
{claim_summary_json}

Score each dimension from 0 to 10, where 0 is unusable and 10 is excellent.

Dimensions:
- coherence: The report directly answers the query with consistent logic.
- cohesion_structure: Sections are organized, non-redundant, and easy to follow.
- analytical_depth: Analysis goes beyond surface facts with useful interpretation.
- professionalism_readability: Writing is clear, polished, and professional.
- decision_usefulness: The report supports practical decisions with relevant takeaways.

Return only one JSON object with this exact shape:

{{
  "coherence": {{"score": 0, "reasoning": "brief reason"}},
  "cohesion_structure": {{"score": 0, "reasoning": "brief reason"}},
  "analytical_depth": {{"score": 0, "reasoning": "brief reason"}},
  "professionalism_readability": {{"score": 0, "reasoning": "brief reason"}},
  "decision_usefulness": {{"score": 0, "reasoning": "brief reason"}}
}}
