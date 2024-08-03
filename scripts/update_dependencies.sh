#!/bin/bash
compat=""
if [[ "$OSTYPE" == "darwin"* ]]; then
    compat=" "
fi

dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd $dir/..
set -xe
rm -f requirements.txt dev-requirements.txt constraints.txt
export CUSTOM_COMPILE_COMMAND=./scripts/update_dependencies.sh
pip-compile --strip-extras constraints.in
pip-compile --strip-extras dev-requirements.in
pip-compile --strip-extras

# Remove the line specifying dallinger as editable dependency
sed -e "s/^-e.*//" -i$compat'' *.txt

# Post-process the constraints.txt and dev-requirements.txt files to replace "via file://..."
# with "via constraints.in" and " via dev-requirements.in", respectively.
sed -i.bak 's|via file://.*|via -r constraints.in|' constraints.txt
sed -i.bak 's|via file://.*|via -r dev-requirements.in|' dev-requirements.txt
