"""Placeholder so pytest collection succeeds before real tests land.

TODO: replace with unit tests for cleaning, imputation, augmentation, and
loader idempotency (using a fixture dataframe + a throwaway pgvector container).
"""


def test_scaffold_imports() -> None:
    from src.pipeline import augmentation, cleaning, embedding, imputation, loader  # noqa: F401
