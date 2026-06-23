#!/bin/sh

dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd $dir/..
set -xe

export UV_CUSTOM_COMPILE_COMMAND=./scripts/update_dependencies.sh
uv pip compile --python-version 3.11 --upgrade constraints.in --output-file constraints.txt
uv pip compile --python-version 3.11 --upgrade dev-requirements.in --output-file dev-requirements.txt
uv pip compile --python-version 3.11 --upgrade requirements.in --output-file requirements.txt

# Remove the line specifying dallinger as editable dependency
sed -e "/^-e/d" -i.bak *.txt
# Fix "via -" annotations
sed -i.bak 's|^    # via -$|    # via -r constraints.in|' constraints.txt
sed -i.bak 's|^    # via -$|    # via -r dev-requirements.in|' dev-requirements.txt

# Cleanup
rm -f constraints.txt.bak dev-requirements.txt.bak requirements.txt.bak
