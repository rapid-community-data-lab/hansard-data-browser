# hansard-data-browser

A notebook based browser for compiled Australian Federal Hansard data.

[Launch in ARDC BinderHub (Requires AAF Login)](https://binderhub.rc.nectar.org.au/v2/gh/rapid-community-data-lab/hansard-data-browser/HEAD?urlpath=%2Fdoc%2Ftree%2Fnotebooks%2Fbrowser.py)


# Updating Dependencies

Abstract dependencies are kept in `pyproject.toml`. You can generate the specific dependencies needed for binderhub in `binder/requirements.txt` using `pip-compile`:

```bash

pip install -e .[dev]
pip-compile pyproject.toml -o binder/requirements.txt

```