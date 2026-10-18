# Windows PowerShell build (needs g++ or clang++ with OpenMP, for example MSYS2 mingw64: pacman -S mingw-w64-x86_64-gcc).
# Builds build\nbody-seq.exe, build\nbody-omp.exe and build\nbody-debug.exe. Same three builds as build.sh.
# Optional: .\build.ps1 -NativeCpu   adds -march=native (only runs on the machine that built it).
param([switch]$NativeCpu)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$cxx = if ($env:CXX) { $env:CXX } else { "g++" }
$src = @("src/nbody.cpp", "src/main.cpp")
# -fno-math-errno: see build.sh. Without it the OpenMP builds run about 50% slower on one thread than the sequential build.
$common = @("-std=c++17", "-Wall", "-Wextra", "-Wpedantic", "-fno-math-errno", "-static")
$native = if ($NativeCpu) { @("-march=native") } else { @() }
New-Item -ItemType Directory -Force build | Out-Null
"compiler: " + (& $cxx --version | Select-Object -First 1)
"== seq";   & $cxx @common "-Wno-unknown-pragmas" "-O2" @native @src -o build/nbody-seq.exe;   if ($LASTEXITCODE) { throw "seq build failed" }
"== omp";   & $cxx @common "-O2" @native "-fopenmp" @src -o build/nbody-omp.exe;              if ($LASTEXITCODE) { throw "omp build failed" }
"== debug"; & $cxx @common "-Wno-unknown-pragmas" "-O0" "-g" @src -o build/nbody-debug.exe;    if ($LASTEXITCODE) { throw "debug build failed" }
Get-ChildItem build | Select-Object Name, Length
