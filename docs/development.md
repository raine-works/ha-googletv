# Development


```bash
pip install -r requirements-test.txt     # parser tests and ruff
pytest -q
pip install -r requirements-test-ha.txt  # with Home Assistant: config flow and setup
pytest -q
```

The parsers (`custom_components/googletv/parsers.py`) are tested on output
captured from real TVs. The TV app is in `android/` (built by CI, attached
to each release); its API is documented in `protocol/README.md`. Sideloaded
builds are signed with a development key kept in the repo.
