#!/bin/bash

mkdir -p docs/demos/
mkdir -p docs/demos/assets
mkdir -p build

cd examples

for filename in *; do
    echo $filename

    # Clean needless files.
    rm $filename/-
    rm $filename/.psiturk_history
    rm -r $filename/snapshots/*

    # Copy over the README.
    cp $filename/README.md ../docs/demos/"$filename.md"

    # Zip up the demo.
    zip -r "$filename.zip" $filename
    cp "$filename.zip" ../build/"$filename.zip"
    cp "$filename.zip" ../docs/demos/assets/"$filename.zip"
    rm "$filename.zip"
done

cd ..

# rm -r build/*
# rm -r docs/demos/*

mkdocs gh-deploy --clean --verbose
