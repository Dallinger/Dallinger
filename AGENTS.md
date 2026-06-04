# Agent contribution notes

This repository expects contributors (including automated agents) to install the
full package with development tooling and to run checks locally before
finalizing a contribution.

## Setup

Install Dallinger with dev dependencies (includes pre-commit, ruff, pytest, tox):

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

### System packages (one-time per VM)

Ubuntu packages needed beyond a stock Python image:

- `python3.12-venv`, `libpq-dev`, `python3-dev`, `build-essential` (editable install / `psycopg2`)
- `postgresql`, `redis-server` (required for most tests and local experiment runs)
- **Google Chrome** (preinstalled on many cloud images at `/usr/local/bin/google-chrome`)
- **Chromedriver** (must match the installed Chrome major version)
- **Heroku CLI** (for `dallinger debug` / `heroku local`)

Install Chromedriver to match `google-chrome --version` (example for Chrome `148.0.7778.96`):

```bash
CHROME_VERSION=$(google-chrome --version | grep -oP '\d+\.\d+\.\d+\.\d+')
curl -fsSL "https://storage.googleapis.com/chrome-for-testing-public/${CHROME_VERSION}/linux64/chromedriver-linux64.zip" -o /tmp/chromedriver.zip
unzip -qo /tmp/chromedriver.zip -d /tmp
sudo mv /tmp/chromedriver-linux64/chromedriver /usr/local/bin/chromedriver
sudo chmod +x /usr/local/bin/chromedriver
chromedriver --version
```

Install Heroku CLI (same as CI):

```bash
curl -fsSL https://cli-assets.heroku.com/install.sh | sh
heroku --version
```

Quick sanity check for Chromedriver: run a headless Selenium session (requires the editable
`dallinger` install, which pulls in `selenium`).

After install, start services before tests or `dallinger develop`:

```bash
sudo service postgresql start
sudo service redis-server start
```

Create the CI-matching database role once (if missing):

```bash
sudo -u postgres psql -c "CREATE USER dallinger WITH PASSWORD 'dallinger' CREATEDB;"
sudo -u postgres psql -c "CREATE DATABASE dallinger OWNER dallinger;"
```

### Environment variables

```bash
export DATABASE_URL=postgresql://dallinger:dallinger@localhost/dallinger
export PORT=5000
```

Demos pin Python in `.python-version` (often 3.13). On 3.12 images, either install that
version or set `SKIP_PYTHON_VERSION_CHECK=1` when running `dallinger develop` / `verify`.

### Python and Node

- Prefer a repo-local venv: `python3 -m venv .venv` then `source .venv/bin/activate`.
- Install: `python -m pip install -e ".[dev]"` and `python -m pip install -e demos`.
- JS: from repo root, `yarn --frozen-lockfile --ignore-engines`, then `npm run test` / `npm run build`.

### Running a demo locally (no Heroku)

From an experiment directory (e.g. `demos/dlgr/demos/bartlett1932`):

```bash
dallinger develop bootstrap
dallinger develop debug --port 5000
```

Recruitment URL (hotair recruiter): `http://127.0.0.1:5000/ad?generate_tokens=true&recruiter=hotair`

`dallinger debug` (classic) needs the Heroku CLI and `heroku local`. Full CI `tox` also
needs Chromedriver, Heroku CLI, and optional AWS/Prolific tokens; use `tox -e fast` for a
lighter Python-only pass when those are unavailable.

### Lint and test quick reference

| Check | Command |
|-------|---------|
| Lint | `python -m pre_commit run --all-files` |
| Python tests | `python -m pytest` (Postgres + Redis running, `DATABASE_URL` set) |
| JS tests | `npm run test` |
| JS build | `npm run build` |
