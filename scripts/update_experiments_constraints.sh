#!/bin/bash
dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd $dir/..

# Command to calculate md5sum of a file. Since BSD (Mac OS) has an `md5` binary and Linux has `md5sum`
# we salomonically decide to ditch both and implement them as a python one liner.
function md5_cmd () {
    python3 -c "import hashlib as h;from sys import argv; print(h.md5(open( argv[1], 'rb').read()).hexdigest())" $1
}

# Update demos constraints
export CUSTOM_COMPILE_COMMAND=$'./scripts/update_experiments_constraints.sh\n#\n# from the root of the dallinger repository'
for demo_name in $(ls demos/dlgr/demos/); do
    if [ -f "demos/dlgr/demos/${demo_name}/config.txt" ]; then
        cd "demos/dlgr/demos/${demo_name}/"
        echo Compiling ${demo_name}
        # Temporarily replace the dallinger package name with the GitHub requirement which includes the release branch
        sed -i "s/^dallinger$/dallinger@git+https:\/\/github.com\/Dallinger\/Dallinger@$(git branch --show-current)/g" requirements.txt
        # Compile constraints.txt file
        pip-compile -o constraints.txt -c ../../../../dev-requirements.txt -r requirements.txt
        # Remove extras from constraints.txt
        sed -e 's/\[.*==/==/' -i constraints.txt
        # Revert dallinger GitHub requirement back to package name
        sed -i "s/^dallinger@git+https:\/\/github.com\/Dallinger\/Dallinger@$(git branch --show-current)$/dallinger/g" requirements.txt
        # Update constraints.txt file to use the to be released dallinger version
        sed -i "s/^dallinger\ @\ git+https:\/\/github.com\/Dallinger\/Dallinger@$(git branch --show-current)$/dallinger==$(dallinger -v)/g" constraints.txt
        echo ""
        echo "# Hash of requirements.txt file:" $(md5_cmd requirements.txt) >> constraints.txt
        cd -
    fi
done

sed -i.orig -e "s/dallinger==.*/dallinger==$(dallinger --version)/" demos/dlgr/demos/*/constraints.txt
