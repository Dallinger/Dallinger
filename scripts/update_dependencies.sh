#!/bin/sh

dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd $dir/..
set -xe

python - <<'PY'
import sys

if sys.version_info[:2] != (3, 11):
    raise SystemExit(
        "Dependency pins must be compiled with Python 3.11, the lowest "
        "supported Python version. Run this script with Python 3.11, for "
        "example: uv run --python 3.11 ./scripts/update_dependencies.sh"
    )
PY

export CUSTOM_COMPILE_COMMAND=./scripts/update_dependencies.sh
pip-compile --rebuild --strip-extras --upgrade constraints.in
pip-compile --rebuild --strip-extras --upgrade dev-requirements.in
pip-compile --rebuild --strip-extras --upgrade

# Remove the line specifying dallinger as editable dependency
sed -e "/^-e/d" -i.bak *.txt
# Fix "via -" annotations
sed -i.bak 's|^    # via -$|    # via -r constraints.in|' constraints.txt
sed -i.bak 's|^    # via -$|    # via -r dev-requirements.in|' dev-requirements.txt

# Cleanup
rm constraints.txt.bak dev-requirements.txt.bak
