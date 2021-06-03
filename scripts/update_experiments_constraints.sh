#!/bin/sh
dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd $dir/..

# Update demos constraints
for demo_name in $(ls demos/dlgr/demos/); do
    if [ -f "demos/dlgr/demos/${demo_name}/config.txt" ]; then
        cd "demos/dlgr/demos/${demo_name}/"
        echo Compiling ${demo_name}
        dallinger generate-constraints
        cd -
    fi
done
