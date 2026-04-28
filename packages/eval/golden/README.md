# Golden Evaluation Set

`golden_set.json` is created in **M8** and contains 100 hand-curated QA pairs
used by the RAGAS offline evaluator and the nightly CI gate.

## Schema

```json
[
  {
    "question":         "I want something like Fullmetal Alchemist with a focus on brotherhood themes",
    "ground_truth":     "Fullmetal Alchemist: Brotherhood is the most direct match ...",
    "reference_mal_ids": [5114, 9919]
  }
]
```

## Adding samples

1. Think of a query a real user would ask.
2. Pick 2–5 anime from `data/anime_with_synopsis.csv` that genuinely answer it.
3. Write `ground_truth` as a 1–3 sentence answer a domain expert would give.
4. Add to `golden_set.json` and run `make eval` to verify the pipeline score holds.
