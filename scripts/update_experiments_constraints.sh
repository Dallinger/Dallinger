#!/bin/sh
dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd $dir/..

# Update demos constraints
for demo_name in $(ls demos/dlgr/demos/); do
    if [ -f "demos/dlgr/demos/${demo_name}/config.txt" ]; then
        cd "demos/dlgr/demos/${demo_name}/"
        echo Compiling ${demo_name}
        echo "-c ../../../../dev-requirements.txt
-r requirements.txt" > temp-requirements.txt
        pip-compile temp-requirements.txt -o constraints.txt
        rm temp-requirements.txt
        cd -
    fi
done

sed -i ".orig" -e "s/dallinger==.*/dallinger==$(dallinger --version)/" demos/dlgr/demos/*/constraints.txt
