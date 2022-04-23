#!/bin/bash

set -e
if [ $# -eq 0 ]; then
    make DEBUG=1 DEVELOPMENT=1 STRICT=1 PROFILE=1 LUA_PROFILER=1 -j
else
    make DEBUG=1 DEVELOPMENT=1 PROFILE=1 LUA_PROFILER=1 -j
fi

# find file
FILE=./build/us_pc/sm64.us.f3dex2e.exe
if [ ! -f "$FILE" ]; then
    FILE=./build/us_pc/sm64.us.f3dex2e
fi

$FILE &