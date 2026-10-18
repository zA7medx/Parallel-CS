#!/usr/bin/env bash
# Builds three variants of the same source tree into build/.
#   build/nbody-seq    sequential build, no OpenMP        (-O2)
#   build/nbody-omp    OpenMP build                       (-O2 -fopenmp)
#   build/nbody-debug  debug build, no optimisation       (-O0 -g, sanitizers when the compiler has them)
# Optional: NATIVE_CPU=1 adds -march=native (x86) or -mcpu=native (Arm). Binaries built that way only run on the
# machine that built them; leave it off when you compare machines with the same flags.
# Optional: CXX=clang++ ./build.sh
set -euo pipefail
cd "$(dirname "$0")"
CXX="${CXX:-g++}"
SRC="src/nbody.cpp src/main.cpp"
# -fno-math-errno: sqrt need not set errno (we never take the root of a negative number). Without it, g++ keeps an errno
# branch inside the OpenMP force loops, cannot compute two square roots at once there, and every OpenMP variant on one
# thread runs about 50% slower than the sequential build (measured 16 Oct 2026). Results are identical with or without it.
COMMON="-std=c++17 -Wall -Wextra -Wpedantic -fno-math-errno"
NATIVE=""
if [ "${NATIVE_CPU:-0}" = "1" ]; then
  case "$(uname -m)" in
    aarch64|arm64) NATIVE="-mcpu=native" ;;
    *) NATIVE="-march=native" ;;
  esac
fi
# On Windows (MSYS2 / MinGW / Git Bash) another libstdc++ DLL earlier on PATH can crash a dynamically linked
# program, so link statically there.
LINK=""
case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) LINK="-static" ;; esac
mkdir -p build
echo "compiler: $($CXX --version | head -n 1)"
echo "== seq";   $CXX $COMMON -Wno-unknown-pragmas -O2 $NATIVE $SRC $LINK -o build/nbody-seq
echo "== omp";   $CXX $COMMON -O2 $NATIVE -fopenmp $SRC $LINK -o build/nbody-omp
echo "== debug"
if $CXX $COMMON -Wno-unknown-pragmas -O0 -g -fsanitize=address,undefined $SRC $LINK -o build/nbody-debug 2>/dev/null; then
  echo "   (with address and undefined-behaviour sanitizers)"
else
  $CXX $COMMON -Wno-unknown-pragmas -O0 -g $SRC $LINK -o build/nbody-debug
  echo "   (sanitizers not available with this compiler; plain debug build)"
fi
ls -1 build
