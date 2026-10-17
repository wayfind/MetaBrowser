# Native MetaBrowser tests are standalone unittest scripts (python tests/integration/<name>.py);
# keep them out of the upstream root `pytest tests/` run.
collect_ignore_glob = ["*"]
