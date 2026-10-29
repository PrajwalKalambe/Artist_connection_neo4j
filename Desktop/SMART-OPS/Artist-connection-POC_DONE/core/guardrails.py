"""
core/guardrails.py

Input-side guardrails. Kept intentionally small and dependency-free so it can
run before anything else in the pipeline (even before the kill switch
check needs a network call).
"""
from config import MAX_INPUT_LENGTH


class GuardRails:

    @staticmethod
    def validate_user_input(user_input: str) -> bool:
        if not user_input or not user_input.strip():
            raise ValueError("Empty query received.")

        if len(user_input) > MAX_INPUT_LENGTH:
            raise ValueError(
                f"Input exceeds {MAX_INPUT_LENGTH} characters."
            )

        return True
