# tests

Regression tests for email-evidence-tools, built on synthetic mbox archives that reproduce the message shapes and interrupted runs that have caused silent failures.

Run them from the repository root:

```bash
pip install -r requirements-dev.txt
pytest
```

Each test names the failure it guards against in its docstring. The tools are exercised the way a user runs them, as command-line scripts, except where a test has to interrupt a run partway through.

- `mbox_builder.py` composes the fixtures: plain, HTML-only, attachment-bearing, and nested-container messages.
- `conftest.py` puts the repository root on `sys.path` so the tools import directly.
