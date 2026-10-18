#!/usr/bin/env bash
# Stage 1 run kit for macOS and Linux. Builds the sequential program if needed, runs it with the team's fixed
# settings, saves a CSV in results/ and prints one block (CPU specification + median times) for the Device form.
#
# Usage, from the nbody-cpp folder:   bash tools/run-stage1.sh "Your Name"
# Needs a C++ compiler: macOS -> xcode-select --install ; Ubuntu/Debian -> sudo apt install g++
set -euo pipefail
cd "$(dirname "$0")/.."

NAME="${1:-${USER:-member}}"
SIZES="${SIZES:-1000 2000 4000 8000}"
STEPS="${STEPS:-50}"
REPEATS="${REPEATS:-5}"
SEED="${SEED:-12345}"
CXX="${CXX:-c++}"

mkdir -p build results
BIN=build/nbody-seq
if [ ! -x "$BIN" ]; then
  if ! command -v "$CXX" >/dev/null 2>&1; then
    echo "No C++ compiler found. macOS: xcode-select --install   Ubuntu/Debian: sudo apt install g++"
    exit 1
  fi
  echo "building $BIN with $CXX -O2 ..."
  "$CXX" -std=c++17 -O2 -Wno-unknown-pragmas src/nbody.cpp src/main.cpp -o "$BIN"
fi
COMPILER="$("$BIN" --info | head -n 1 | sed 's/^compiler: //')"

ARCH="$(uname -m)"
case "$(uname -s)" in
  Darwin)
    OS="macOS $(sw_vers -productVersion)"
    CPU="$(sysctl -n machdep.cpu.brand_string 2>/dev/null || echo unknown)"
    CORES="$(sysctl -n hw.physicalcpu) physical / $(sysctl -n hw.logicalcpu) logical"
    P=$(sysctl -n hw.perflevel0.physicalcpu 2>/dev/null || true); E=$(sysctl -n hw.perflevel1.physicalcpu 2>/dev/null || true)
    [ -n "$P" ] && [ -n "$E" ] && CORES="$CORES ($P performance + $E efficiency)"
    CLOCK="$(sysctl -n hw.cpufrequency_max 2>/dev/null | awk '{printf "%d MHz", $1/1e6}' || true)"
    [ -z "$CLOCK" ] && CLOCK="not reported (Apple Silicon)"
    CACHE="L2 $(( $(sysctl -n hw.l2cachesize 2>/dev/null || echo 0) / 1024 )) KB / L3 $(( $(sysctl -n hw.l3cachesize 2>/dev/null || echo 0) / 1024 )) KB"
    RAM="$(( $(sysctl -n hw.memsize) / 1073741824 )) GB"
    if pmset -g batt 2>/dev/null | grep -q "AC Power"; then POWER="plugged in or desktop"; else POWER="ON BATTERY (plug in and run again)"; fi
    ;;
  *)
    OS="$( (. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME") || uname -sr)"
    CPU="$(lscpu | awk -F: '/Model name/ {gsub(/^ +/, "", $2); print $2; exit}')"
    SOCK="$(lscpu | awk -F: '/^Socket\(s\)/ {gsub(/ /, "", $2); print $2; exit}')"
    CPS="$(lscpu | awk -F: '/Core\(s\) per socket/ {gsub(/ /, "", $2); print $2; exit}')"
    CORES="$(( ${SOCK:-1} * ${CPS:-0} )) physical / $(nproc --all) logical"
    CLOCK="$(lscpu | awk -F: '/CPU max MHz/ {gsub(/ /, "", $2); printf "%d MHz", $2; exit}')"
    [ -z "$CLOCK" ] && CLOCK="not reported"
    CACHE="L2 $(lscpu | awk -F: '/^L2 cache/ {gsub(/^ +/, "", $2); print $2; exit}') / L3 $(lscpu | awk -F: '/^L3 cache/ {gsub(/^ +/, "", $2); print $2; exit}')"
    RAM="$(awk '/MemTotal/ {printf "%.1f GB", $2/1048576}' /proc/meminfo)"
    POWER="$( (cat /sys/class/power_supply/A*/online 2>/dev/null || true) | head -n 1 | sed 's/1/plugged in/;s/0/ON BATTERY (plug in and run again)/')"
    [ -z "$POWER" ] && POWER="desktop, VM or not reported"
    ;;
esac

echo
echo "Stage 1 sequential benchmark - $CPU"
echo "Keep the charger plugged in, close other programs and do not use the computer until it finishes."
echo "Settings: sizes $SIZES, steps $STEPS, repeats $REPEATS, seed $SEED"
echo

SAFE="$(printf '%s' "$NAME" | tr -cd 'A-Za-z0-9_-')"; [ -z "$SAFE" ] && SAFE=member
CSV="results/S1_${SAFE}_$(hostname -s 2>/dev/null || hostname)_$(date +%Y%m%d-%H%M).csv"
echo "variant,grain,schedule,threads,n,steps,seed,repeat,seconds,pe_last,energy_drift" > "$CSV"
SUMMARY=""
PREV=""
for N in $SIZES; do
  printf "  running n = %s ..." "$N"
  OUT="$("$BIN" --csv --n "$N" --steps "$STEPS" --repeats "$REPEATS" --seed "$SEED")"
  echo "$OUT" >> "$CSV"
  # median = middle value after sorting (same rule as the C++ program and bench.py)
  STATS="$(echo "$OUT" | cut -d, -f9 | sort -g | awk '{a[NR]=$1} END {printf "%.4f %.4f %.4f", a[int(NR/2)+1], a[1], a[NR]}')"
  MED="${STATS%% *}"
  GROWTH=""
  [ -n "$PREV" ] && GROWTH="$(awk -v a="$MED" -v b="$PREV" 'BEGIN {printf "%.2fx", a/b}')"
  SUMMARY="$SUMMARY$(printf '%-7s %10s %10s %10s %8s' "$N" $STATS "$GROWTH")"$'\n'
  PREV="$MED"
  echo " median $MED s"
done

BLOCK="===== Stage 1 result (copy from here) =====
Member       : $NAME
Machine      : $(hostname)
OS           : $OS ($ARCH)
CPU          : $CPU
Cores        : $CORES
Max clock    : $CLOCK
Cache        : $CACHE
RAM          : $RAM
Power        : $POWER
Binary       : own build ($BIN), $COMPILER
Settings     : steps=$STEPS repeats=$REPEATS seed=$SEED (time = median)

N         median_s      min_s      max_s   growth
${SUMMARY}
CSV file     : $CSV
===== (copy until here) ====="

echo
echo "$BLOCK"
if command -v pbcopy >/dev/null 2>&1; then printf '%s\n' "$BLOCK" | pbcopy; echo; echo "The block above is already copied. Paste it into the Device form (Stage 1 result box).";
elif command -v xclip >/dev/null 2>&1; then printf '%s\n' "$BLOCK" | xclip -selection clipboard; echo; echo "The block above is already copied.";
else echo; echo "Select the block above and copy it by hand."; fi
echo "Then upload $CSV to the OneDrive folder 11-Project-Stage1/2-Benchmarks."
