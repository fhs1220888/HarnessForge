# slugify(text: str, max_len: int = 40) -> str

1. Lowercase the input.
2. Replace every run of non-alphanumeric characters with a single hyphen.
3. Strip leading/trailing hyphens.
4. Truncate to at most `max_len` characters; if truncation lands mid-word,
   cut at the last hyphen within the limit instead (if any hyphen exists).
5. An input with no alphanumeric characters returns "".
