"""
Newline-delimited JSON event helpers for the streaming audit endpoint.

`ProgressTracker` is new: it gives the frontend a stable `step`/`total_steps`
counter (e.g. "11/20") alongside the existing percentage, instead of the
percentage being the only signal. Total steps = number of models *
STEPS_PER_MODEL, decided up front, so the counter only ever moves forward
and never resets/jumps around as tool-calling loops of varying length run.
"""

import json

from .constants import STEPS_PER_MODEL


def _emit(**fields) -> str:
    return json.dumps(fields) + "\n"


def status_event(
    message: str,
    progress_pct: int,
    step: int | None = None,
    total_steps: int | None = None,
) -> str:
    fields = dict(
        type="status",
        color="#4f46e5",
        status="progress",
        message=message,
        progress_pct=progress_pct,
    )
    if step is not None and total_steps is not None:
        fields["step"] = step
        fields["total_steps"] = total_steps
        fields["progress_label"] = f"{step}/{total_steps}"
    return _emit(**fields)


def result_event(message: str, report) -> str:
    return _emit(
        type="result",
        color="#22c55e",
        status="completed",
        message=message,
        report=report,
        progress_pct=100,
    )


def model_warning_event(model_name: str, error: Exception) -> str:
    return _emit(
        type="error",
        color="#f59e0b",
        status="warning",
        message=f"{model_name} failed: {str(error)}",
    )


def error_event(message: str) -> str:
    return _emit(type="error", color="#ef4444", status="failed", message=message)


def failed_event(message: str) -> str:
    return json.dumps({"status": "failed", "message": message}) + "\n"


class ProgressTracker:
    """Tracks a monotonically increasing step counter across N models, each
    contributing STEPS_PER_MODEL discrete checkpoints, and renders it both
    as a percentage and as an "X/Y" label for the frontend progress bar.
    """

    def __init__(self, total_models: int, steps_per_model: int = STEPS_PER_MODEL):
        self.total_models = max(total_models, 1)
        self.steps_per_model = steps_per_model
        self.total_steps = self.total_models * self.steps_per_model
        self.current_step = 0

    def tick(self, message: str) -> str:
        self.current_step = min(self.current_step + 1, self.total_steps)
        progress_pct = int((self.current_step / self.total_steps) * 100)
        return status_event(message, progress_pct, self.current_step, self.total_steps)

    def set_model_index(self, model_index: int) -> None:
        """Snap the counter to the start of a given model's block, in case a
        prior model finished early/late relative to STEPS_PER_MODEL."""
        self.current_step = model_index * self.steps_per_model
