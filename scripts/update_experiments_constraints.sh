#!/bin/sh
dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd $dir/..

# Update demos constraints
for demo_name in $(ls demos/dlgr/demos/); do
    if [ -f "demos/dlgr/demos/${demo_name}/config.txt" ]; then
        cd "demos/dlgr/demos/${demo_name}/"
        if [ "${demo_name}" = "bartlett1932" ]; then
            # The bartlett1932 experiment is used in docker tests.
            # Its constraints should always be aligned with the ones specified for dallinger
            # in its `requirements.txt`. Hence the special treatment here.
            echo bartlett1932 experiment: copy versions from current "requirements.txt"
            cp $dir/../requirements.txt "$dir/../demos/dlgr/demos/${demo_name}/constraints.txt"
            # Let everyone know this file is up to date.
            # `dallinger.utils.ensure_constraints_file_presence` will check this
            printf "\ndallinger\n# No dallinger== version here\n#Compiled from requirements file with md5sum: $(md5sum "$dir/../demos/dlgr/demos/${demo_name}/requirements.txt")\n" >> "$dir/../demos/dlgr/demos/${demo_name}/constraints.txt"
        else
            echo Compiling ${demo_name}
            dallinger generate-constraints
        fi
        cd -
    fi
done

sed -i ".orig" -e "s/dallinger==.*/dallinger==$(dallinger --version)/" demos/dlgr/demos/*/constraints.txt
