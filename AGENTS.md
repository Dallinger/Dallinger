# Agent contribution notes

This repository expects contributors (including automated agents) to install the
full package with development tooling and to run checks locally before
finalizing a contribution.

## Setup

Install Dallinger with dev dependencies (includes pre-commit, black, pytest, tox):

```bash
python -m pip install -e ".[dev]"
```

If you need additional optional functionality (e.g., `ec2`, `docker`, `jupyter`),
install those extras as needed:

```bash
python -m pip install -e ".[dev,ec2,docker]"
```

## Pre-commit

Run the full pre-commit suite before submitting changes:

```bash
python -m pre_commit run --all-files
```

## Tests

Run tests locally before finalizing a contribution:

```bash
python -m pytest
```

For the full matrix used in CI, run:

```bash
tox
```

## Cursor Cloud specific instructions

### Required services

PostgreSQL and Redis must be running before tests or the experiment server can start:

```bash
sudo pg_ctlcluster 16 main start
sudo redis-server --daemonize yes
```

The database expects user `dallinger` with password `dallinger` and database `dallinger`:

```bash
# Only needed on first setup; already done in the VM snapshot
sudo -u postgres createuser -P dallinger --createdb  # password: dallinger
sudo -u postgres createdb -O dallinger dallinger
```

Set the database URL before running tests:

```bash
export DATABASE_URL="postgresql://dallinger:dallinger@localhost/dallinger"
```

### Running tests

```bash
# Python tests (782 pass, 344 skipped, 10 failures on Python 3.12 due to .python-version mismatch)
python3 -m pytest tests

# JavaScript tests
npm run test

# Lint checks
python3 -m flake8
python3 -m black --check dallinger dallinger_scripts demos tests
```

Note: 10 tests in `tests/test_command_line.py` fail on Python 3.12 because the bartlett1932 demo's `.python-version` specifies 3.13. These pass on Python 3.13 in CI.

### Running the experiment server

The server can be started directly from a demo experiment directory:

```bash
cd demos/dlgr/demos/bartlett1932
export FLASK_SECRET_KEY="some-secret"
export PORT=5000
gunicorn --worker-class gevent --bind 0.0.0.0:5000 'dallinger.experiment_server.sockets:app'
```

The full `dallinger debug` command requires Heroku CLI. For development without Heroku, use `dallinger develop debug` from an experiment directory, or start gunicorn directly as shown above.

### Key environment variables

- `DATABASE_URL` — PostgreSQL connection string (default: `postgresql://dallinger:dallinger@localhost/dallinger`)
- `FLASK_SECRET_KEY` — Required for the Flask web server
- `PORT` — Server port (default: 5000)
- `PATH` must include `$HOME/.local/bin` for pip-installed scripts (`dallinger`, `pre-commit`, etc.)

### Dependencies

Use `python3` (not `python`) as the command — no `python` symlink exists in this environment. Install all extras for running the full test suite:

```bash
pip install -e ".[dev,data,docker,ec2]"
pip install -e demos
yarn --frozen-lockfile --ignore-engines
```
