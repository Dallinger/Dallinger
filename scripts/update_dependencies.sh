#!/bin/sh

dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd $dir/..
set -xe
export CUSTOM_COMPILE_COMMAND=./scripts/update_dependencies.sh
pip-compile --rebuild --strip-extras --upgrade constraints.in
pip-compile --rebuild --strip-extras --upgrade dev-requirements.in
pip-compile --rebuild --strip-extras --upgrade

# Remove the line specifying dallinger as editable dependency
sed -e "s/^-e.*//" -i.bak *.txt

# Post-process the constraints.txt and dev-requirements.txt files to replace "via file://..."
# with "via constraints.in" and " via dev-requirements.in", respectively.
sed -i.bak 's|via file://.*|via -r constraints.in|' constraints.txt
sed -i.bak 's|via file://.*|via -r dev-requirements.in|' dev-requirements.txt

# Cleanup
rm constraints.txt.bak dev-requirements.txt.bak
