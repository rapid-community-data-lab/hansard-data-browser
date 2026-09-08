# hansard-data-browser

A notebook based browser for compiled Australian Federal Hansard data.




# Updating Dependencies

Abstract dependencies are kept in `pyproject.toml`. You can generate the specific dependencies needed for binderhub in `binder/requirements.txt` using `pip-compile`:

```bash

pip install -e .[dev]
pip-compile pyproject.toml -o binder/requirements.txt

```