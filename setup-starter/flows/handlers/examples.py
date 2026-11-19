"""Handlers of the setup folder's example flows. Each is a plain function: neorc hands it the
step's params, and keeps what it returns as the step's output."""


def hello(name: str) -> str:
    """The greeting of hello.yaml: no model, no conversation."""
    return f"Hello, {name.strip() or 'you'}"
