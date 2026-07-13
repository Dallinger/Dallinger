#!/bin/sh

dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd $dir/..
set -xe

target_python=3.11
export UV_CUSTOM_COMPILE_COMMAND=./scripts/update_dependencies.sh
uv pip compile --python-version "$target_python" --upgrade constraints.in --output-file constraints.txt
uv pip compile --python-version "$target_python" --upgrade dev-requirements.in --output-file dev-requirements.txt
uv pip compile --python-version "$target_python" --upgrade requirements.in --output-file requirements.txt

python - <<PY
from pathlib import Path

target_python = "$target_python"
for name in ["constraints.txt", "dev-requirements.txt", "requirements.txt"]:
    path = Path(name)
    text = path.read_text()
    marker = "#    ./scripts/update_dependencies.sh\n"
    path.write_text(text.replace(marker, marker + f"# Compiled for Python {target_python}\n", 1))
PY

# Remove the line specifying dallinger as editable dependency
sed -e "/^-e/d" -i.bak *.txt
# Fix "via -" annotations
sed -i.bak 's|^    # via -$|    # via -r constraints.in|' constraints.txt
sed -i.bak 's|^    # via -$|    # via -r dev-requirements.in|' dev-requirements.txt

# Cleanup
rm -f constraints.txt.bak dev-requirements.txt.bak requirements.txt.bak
