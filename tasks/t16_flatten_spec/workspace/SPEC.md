# flatten(obj, sep=".", max_depth=None) -> dict

Flatten a nested structure of dicts and lists into a single-level dict.

1. Nested dict keys are joined with `sep`: `{"a": {"b": 1}}` -> `{"a.b": 1}`.
2. Lists use the element index as the key segment: `{"a": [10, 20]}` ->
   `{"a.0": 10, "a.1": 20}`.
3. A key that itself CONTAINS the separator must have each occurrence escaped
   with a backslash: `{"a.b": 1}` -> `{"a\.b": 1}`.
4. Empty dicts and empty lists are preserved as leaf values:
   `{"a": {}}` -> `{"a": {}}`.
5. If `max_depth` is given, stop descending at that depth and keep the
   remaining substructure as the value. Depth 1 means only the top level is
   flattened.
6. Scalars passed directly (non-dict, non-list) raise TypeError.
7. Key order in the result follows depth-first, insertion order.
