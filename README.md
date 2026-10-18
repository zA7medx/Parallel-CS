# N-body simulation in C++ with OpenMP

**Parallelising a direct N-body simulation: synchronisation methods compared on x86-64 and Arm CPUs**
ARTI 503 Parallel Architecture and Programming, Group 3 (sections 9MS2 and 9MS3), College of Computer Science and Information Technology, Imam Abdulrahman Bin Faisal University, Term 1 2026-2027.

Direct-summation N-body simulation with softened gravity and a leapfrog integrator. One source tree, three builds, and four ways of protecting the shared potential-energy total in the OpenMP version. The method, the measurements and the plan are in the group's Stage 1 report.

## Files

| File | Purpose |
|---|---|
| `src/nbody.hpp`, `src/nbody.cpp` | System arrays, seeded input, force kernels, leapfrog step |
| `src/main.cpp` | Command line, timing, CSV output, correctness check |
| `build.sh`, `build.ps1` | Linux / macOS / MSYS2 build and Windows PowerShell build |
| `bin/windows-x64/nbody-seq.exe` | Prebuilt sequential build for Windows (g++ 15.1.0, `-O2`, static), so every Windows member runs the same file |
| `Run-Stage1-Windows.bat`, `tools/run-stage1.ps1`, `tools/run-stage1.sh` | Stage 1 run kit: fixed settings, CPU specification and median times in one block |
| `tools/cpuinfo.py` | Prints the CPU specification of the machine |
| `tools/bench.py` | Runs a grid of configurations, repeats each, writes a CSV and prints medians |
| `tools/profile_phases.cpp` | Time of the force loop against the three short update loops (a separate program; it does not change the benchmark) |
| `tools/stage1_results.py` | Tables and figures from the members' run-kit results (needs Python 3 with matplotlib) |

## Stage 1 run kit

The Stage 1 handout asks every member to run the sequential code and report the time and the CPU specification. The kit fixes the settings so the numbers can be compared: N = 1000, 2000, 4000, 8000 bodies, 50 steps, 5 repeats, seed 12345, `-O2`, time = median of the 5 runs.

```
Run-Stage1-Windows.bat                      # Windows: double-click, type your name
bash tools/run-stage1.sh "Your Name"        # macOS / Linux (builds build/nbody-seq with c++ -O2 first)
```

It prints one block (OS, CPU, cores and threads, clock, cache, RAM, power state, binary, median times and the growth when N doubles), copies it to the clipboard, and writes `results/S1_<name>_<machine>_<time>.csv` with every single run. Change the settings only by group decision; the scripts take `-Sizes/-Steps/-Repeats` (PowerShell) or `SIZES/STEPS/REPEATS` (environment, shell).

All 11 members ran it for Stage 1: ten on Windows 11 with the prebuilt binary, one on Arch Linux with the shell kit (g++ 16.2.1). Not tested: macOS (the shell script has a macOS branch using `sysctl`) and Windows on Arm (the x64 binary runs under emulation there and is slower, so such a laptop should build natively or note it).

To make the tables and figures from the members' results:

```
python tools/stage1_results.py --in <folder with S1_*.csv> --specs <folder with the run-kit texts> --out <folder> --no-docx
```

## Build

```
./build.sh            # Linux, macOS, WSL, MSYS2 / Git Bash
.\build.ps1           # Windows PowerShell (g++ from MSYS2 mingw64 in PATH)
```

| Build | Flags | Use |
|---|---|---|
| `build/nbody-seq` | `-O2 -fno-math-errno`, no OpenMP | Sequential baseline for the parallel experiments |
| `build/nbody-omp` | `-O2 -fno-math-errno -fopenmp` | Parallel variants |
| `build/nbody-debug` | `-O0 -g` (sanitizers when available) | Finding bugs, not timing |

`-fno-math-errno` was added on 16 October 2026 (see "Verification"). Compare a parallel run only with a sequential build made with the same flags on the same machine.

`NATIVE_CPU=1 ./build.sh` adds `-march=native` (`-mcpu=native` on Arm). Such binaries run only on the machine that built them. When you compare machines, keep the flags the same and write them in the report. On Windows with Git Bash and MSYS2 together, the scripts link statically because a second `libstdc++` DLL earlier on PATH crashed dynamically linked builds in testing.

## Run

```
build/nbody-seq --n 2000 --steps 100 --repeats 5
build/nbody-omp --variant reduction --threads 4 --n 2000 --steps 100 --repeats 5 --check --tol <your tolerance>
build/nbody-omp --variant unsafe --grain pair --threads 4 --n 800 --steps 20 --check --tol <your tolerance>
python tools/cpuinfo.py
python tools/bench.py --seq-binary build/nbody-seq --sizes 1000,2000,4000 --steps 50 --repeats 5
```

`--help` lists every option. `--info` prints compiler and OpenMP details. The timer covers only the step loop.

## The variants

| `--variant` | Shared total is updated by | Expected |
|---|---|---|
| `seq` | one thread | reference |
| `unsafe` | all threads, no protection (a data race) | wrong accumulated energy; demonstration only |
| `critical` | `#pragma omp critical` | correct, threads wait |
| `atomic` | `#pragma omp atomic` | correct |
| `reduction` | private partial sums, combined once | correct |

`--grain body` updates the shared total once per body (N updates per step). `--grain pair` updates it for every pair (about N\*N per step), which makes the cost of `critical` and `atomic` visible. The `reduction` variant ignores `--grain`. Loop scheduling is `--schedule static|dynamic|guided` with `--chunk`.

## Correctness

The race corrupts the shared energy total, not the positions: the force on each body is written only by the thread that owns that body. `--check` therefore compares two things with the sequential run: the largest position difference and the relative error of the accumulated potential energy. A floating-point sum can change in the last digits when the order of addition changes, so the tolerance must be chosen **before measuring** and justified; the Stage 1 report (Section 6.3) sets it. There is no default on purpose.

## Verification

- **Build:** g++ 15.1.0 (MSYS2) on Windows 11; `-Wall -Wextra -Wpedantic` gives no warnings.
- **The prebuilt program matches the source:** a fresh `g++ -O2 -static` build and `bin/windows-x64/nbody-seq.exe` give the same result to the last digit (N = 1000, 20 steps: accumulated potential energy −4.619508233792e−01, energy drift 3.33e−11).
- **Parallel variants** (8 threads, 20 steps, against the sequential run): `reduction` relative energy error 3.6e−16 (N = 1000) and 1.2e−15 (N = 2000); `critical` and `atomic` at pair grain 1.8e−14 and 2.4e−14 (N = 1000); positions identical in every case. `unsafe --grain pair` (N = 800): 8.7e−01, so it fails, as it should.
- **Where the time goes** (`tools/profile_phases.cpp`, kit settings, AMD Ryzen 7 9700X): the force loop is 99.85% (N = 1000) to 99.98% (N = 8000) of the step time; the three update loops are 0.15% to 0.02%, below the 3.5% to 5% run-to-run spread.
- **`-fno-math-errno`:** without it, every OpenMP variant on 1 thread took 0.240 s against 0.158 s for `--variant seq` (g++ 15.1.0, N = 2000, 20 steps). `-fopt-info-vec` showed why: `std::sqrt` may set `errno`, so g++ keeps a branch inside the force loop of each OpenMP function and does not compute two square roots at once there, while the plain sequential loop is vectorised. With the flag all variants are vectorised, the 1-thread times match (0.156 to 0.160 s against 0.154 s), and the energies are identical to the last digit. The sequential program runs at the same speed with or without it (0.153 s against 0.154 s), so the Stage 1 times are not affected.
- **Synchronisation cost** (8 threads, N = 4000, 10 steps; indicative only, measured on a desktop that was running other programs): with `--grain body`, critical 0.099 s, atomic 0.100 s, reduction 0.096 s; with `--grain pair`, critical 5.7 s and atomic 4.3 s against 0.093 s for reduction, 46 to 60 times slower.

```
g++ -std=c++17 -O2 -Wno-unknown-pragmas -static tools/profile_phases.cpp src/nbody.cpp -Isrc -o build/profile-phases
build/profile-phases                 # defaults: N = 1000,2000,4000,8000, 50 steps, 5 repeats, seed 12345
```

`gprof` gave an empty profile with MinGW on Windows, so the profiling tool times the parts directly.

Not tested yet: macOS, Linux on Arm, Windows on Arm, clang, the sanitizer build.

## Planned

- Newton's-third-law version (half the pair work, which creates write conflicts on the force arrays)
- Array-of-structures layout and padding against false sharing (a short optional test)
- Input sizes for the parallel runs: the Stage 1 sizes plus N = 16 000
- A plotting or animation script for the snapshot file (the writer itself works: `--snapshot file.csv --snapshot-every 10`)
