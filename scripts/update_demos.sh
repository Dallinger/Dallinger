#!/bin/bash

# Script to create/update uv.lock files for all Dallinger demo experiments
# This enables full uv-based dependency management for demos

set -e

dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd $dir/..
project_root=$(pwd)

# Ensure uv is available
if ! command -v uv &> /dev/null; then
    echo "Error: uv is not installed. Please install uv first."
    echo "Run: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

export PATH="$HOME/.local/bin:$PATH"

echo "🔄 Creating/updating uv.lock files for all demo experiments..."

# Create a temporary directory for uv operations
TEMP_DIR=$(mktemp -d)
trap "rm -rf $TEMP_DIR" EXIT

# Count total demos for progress tracking
total_demos=$(find demos/dlgr/demos -maxdepth 1 -type d -name "*" | grep -v __pycache__ | wc -l)
current_demo=0

for demo_dir in demos/dlgr/demos/*/; do
    if [ -d "$demo_dir" ]; then
        demo_name=$(basename "$demo_dir")

        # Skip __pycache__ and other non-demo directories
        if [[ "$demo_name" == "__pycache__" ]]; then
            continue
        fi

        current_demo=$((current_demo + 1))
        echo "📦 Processing ${demo_name} (${current_demo}/${total_demos})..."

        # Create pyproject.toml in the demo directory
        cat > "$project_root/${demo_dir}pyproject.toml" << EOF
[project]
name = "${demo_name}-demo"
version = "0.1.0"
description = "Dallinger demo experiment: ${demo_name}"
requires-python = ">=3.10"
dependencies = [
    "dallinger",
]
EOF

        # Change to demo directory for uv operations
        cd "$project_root/${demo_dir}"

        # Generate uv.lock for this demo
        if ! uv lock --upgrade; then
            echo "❌ Failed to generate lockfile for ${demo_name}"
            cd "$project_root"
            continue
        fi

        # Return to project root for next iteration
        cd "$project_root"

        echo "✅ ${demo_name} uv.lock generated/updated"
    fi
done

echo "🎉 All demo uv.lock files created/updated successfully!"
echo "Processed ${current_demo} demos out of ${total_demos} total demos."
echo ""
echo "To use a demo with uv:"
echo "  cd demos/dlgr/demos/<demo_name>"
echo "  uv sync --frozen"
echo ""
echo "To run a demo:"
echo "  cd demos/dlgr/demos/<demo_name>"
echo "  uv run dallinger debug"
