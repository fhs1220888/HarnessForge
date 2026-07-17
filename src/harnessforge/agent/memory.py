"""Episode-scoped task memory. FIXED runtime code in v1; its knobs live in
loop_policy.yaml (memory.*) so the self-harness loop can tune them.

Why this exists: context compaction (context.py) truncates old tool results to
stay under budget, which silently destroys information the agent may still need
(file paths, root causes, the plan). TaskMemory is durable storage *outside* the
message history: the agent writes notes via the `memory_write` tool, and the
rendered notes are appended to the system prompt on every LLM call — so they
survive compaction by construction, at a bounded token cost.

Scope is deliberately per-episode. Cross-task memory is out of scope for v1:
the benchmark is self-contained tasks, so a persistent store would add machinery
with no measurable benefit (same reasoning as the graphify verdict).

Semantics:
- keyed notes; writing an existing key overwrites it (an update, not a duplicate)
- FIFO eviction beyond max_notes; content truncated at max_chars_per_note
- every write returns a confirmation string the model can read (including any
  eviction/truncation), so the bounds are observable, not silent
"""

from __future__ import annotations

HEADER = "# Task memory (notes you saved; survives context compaction)"


class TaskMemory:
    def __init__(self, max_notes: int = 20, max_chars_per_note: int = 1000):
        self.max_notes = max(1, max_notes)
        self.max_chars_per_note = max(1, max_chars_per_note)
        self._notes: dict[str, str] = {}  # insertion-ordered (py3.7+)

    def __len__(self) -> int:
        return len(self._notes)

    def write(self, key: str, content: str) -> str:
        """Store a note; return a confirmation the model can read."""
        extras = []
        if len(content) > self.max_chars_per_note:
            content = content[: self.max_chars_per_note]
            extras.append(f"truncated to {self.max_chars_per_note} chars")

        if key in self._notes:
            self._notes[key] = content
            verb = "updated"
        else:
            if len(self._notes) >= self.max_notes:
                evicted = next(iter(self._notes))
                del self._notes[evicted]
                extras.append(f"evicted oldest note {evicted!r} (max_notes={self.max_notes})")
            self._notes[key] = content
            verb = "saved"

        suffix = f" ({'; '.join(extras)})" if extras else ""
        return f"Memory {verb}: {key!r} — {len(self._notes)}/{self.max_notes} notes{suffix}"

    def render(self) -> str:
        """System-prompt suffix ('' when empty). Appended on every LLM call."""
        if not self._notes:
            return ""
        lines = [f"- {k}: {v}" for k, v in self._notes.items()]
        return "\n\n" + HEADER + "\n" + "\n".join(lines)
