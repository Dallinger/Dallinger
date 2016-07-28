#!/bin/bash

mkdir -p docs/demos/assets
mkdir -p build

cd examples

for filename in *; do
    echo $filename
    cp $filename/README.md ../docs/demos/"$filename.md"
    zip -r "$filename.zip" $filename
    cp "$filename.zip" ../build/"$filename.zip"
    cp "$filename.zip" ../docs/demos/assets/"$filename.zip"
done

cd ..
