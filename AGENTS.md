# Agent contribution notes

This repository expects contributors (including automated agents) to install the
full package with development tooling and to run checks locally before
finalizing a contribution.

## Setup

Install Dallinger with dev dependencies (includes pre-commit, ruff, pytest, tox):

```bash
python -m pip install -e ".[dev]"
python -m pip install -e demos
```

If you need additional optional functionality (e.g., `ec2`, `docker`, `jupyter`),
install those extras as needed:

```bash
python -m pip install -e ".[dev,ec2,docker]"
```

System dependencies (PostgreSQL, Redis, Heroku CLI, Chromedriver, Node/Yarn) and
local experiment workflows are documented in the
[developer installation guide](https://dallinger.readthedocs.io/en/latest/developing_dallinger_setup_guide.html).

## Pre-commit

Run the full pre-commit suite before submitting changes:

```bash
python -m pre_commit run --all-files
```

## Tests

Run tests locally before finalizing a contribution:

```bash
export DATABASE_URL=postgresql://dallinger:dallinger@localhost/dallinger
export PORT=5000
python -m pytest
```

For the full matrix used in CI, run:

```bash
tox
```

See [running the tests](https://dallinger.readthedocs.io/en/latest/running_the_tests.html)
for pytest/tox options, Chromedriver requirements, and integration-test credentials.

## Cursor Cloud specific instructions

Cloud VMs need the same prerequisites as a local Ubuntu dev environment; follow
the [Ubuntu section of the developer installation guide](https://dallinger.readthedocs.io/en/latest/developing_dallinger_setup_guide.html#ubuntu).

Cloud-agent notes that are not covered there:

- Ensure `python3-venv` and `libpq-dev` are installed before the editable install.
- Start Postgres and Redis before tests or experiment runs:
  `sudo service postgresql start` and `sudo service redis-server start`.
- Prefer a repo-local virtualenv: `python3 -m venv .venv` then
  `source .venv/bin/activate`.
- The VM **update script** refreshes Python and Yarn dependencies only; it does
  not start services, run migrations, or execute tests.
