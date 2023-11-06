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
pip-compile constraints.in
pip-compile dev-requirements.in
pip-compile

# Remove the line specifying dallinger as editable dependency
sed -e "s/^-e.*//" -i$compat'' *.txt

# Remove the extras from constraints.txt, dev-requirements.txt, and requirements.txt
sed -e 's/\[.*==/==/' -i$compat'' constraints.txt
sed -e 's/\[.*==/==/' -i$compat'' dev-requirements.txt
sed -e 's/\[.*==/==/' -i$compat'' requirements.txt
# It prevents this error:
# Constraints are only allowed to take the form of a package name and a version specifier.
# Other forms were originally permitted as an accident of the implementation, but were undocumented.
# The new implementation of the resolver no longer supports these forms.
# A possible replacement is replacing the constraint with a requirement. 
# You can find discussion regarding this at https://github.com/pypa/pip/issues/8210.
# ERROR: Constraints cannot have extras
