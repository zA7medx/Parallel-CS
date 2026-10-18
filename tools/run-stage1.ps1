# Stage 1 run kit for Windows. Runs the sequential N-body program with the team's fixed settings, saves a CSV
# in results\ and prints one block (CPU specification + median times) to paste into the team Device form.
#
# Easiest: double-click "Run-Stage1-Windows.bat" in the nbody-cpp folder (extract the zip first).
# Or from PowerShell in the nbody-cpp folder:
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\run-stage1.ps1 -Name "Your Name"
#
# Binary used: bin\windows-x64\nbody-seq.exe (prebuilt with g++ 15.1.0 -O2, the same file for every Windows member),
# or build\nbody-seq.exe if you pass -UseOwnBuild after running build.ps1.
param(
    [string]$Name = $env:USERNAME,
    [string]$Sizes = "1000,2000,4000,8000",
    [int]$Steps = 50,
    [int]$Repeats = 5,
    [int]$Seed = 12345,
    [switch]$UseOwnBuild
)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

$exe = "bin\windows-x64\nbody-seq.exe"
$binaryNote = "prebuilt bin\windows-x64\nbody-seq.exe"
if ($UseOwnBuild -or -not (Test-Path $exe)) {
    $exe = "build\nbody-seq.exe"
    $binaryNote = "own build (build\nbody-seq.exe)"
    if (-not (Test-Path $exe)) {
        if (-not (Get-Command g++ -ErrorAction SilentlyContinue)) {
            throw "No prebuilt binary and no g++ found. Use the team kit zip, which contains bin\windows-x64\nbody-seq.exe."
        }
        New-Item -ItemType Directory -Force build | Out-Null
        & g++ -std=c++17 -O2 -Wno-unknown-pragmas -static src/nbody.cpp src/main.cpp -o $exe
        if ($LASTEXITCODE) { throw "build failed" }
    }
}
$compiler = ((& $exe --info) | Select-Object -First 1) -replace "^compiler: ", ""

# CPU, memory, OS, power
$cpus = @(Get-CimInstance Win32_Processor)
$cpu = $cpus[0]
$cores = ($cpus | Measure-Object -Property NumberOfCores -Sum).Sum
$logical = ($cpus | Measure-Object -Property NumberOfLogicalProcessors -Sum).Sum
$ramGB = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1)
$os = Get-CimInstance Win32_OperatingSystem
$arch = $env:PROCESSOR_ARCHITECTURE
if ($env:PROCESSOR_ARCHITEW6432) { $arch = $env:PROCESSOR_ARCHITEW6432 }
$battery = @(Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue)
if ($battery.Count -eq 0) { $power = "no battery (desktop)" }
elseif ($battery[0].BatteryStatus -eq 2) { $power = "laptop, plugged in" }
else { $power = "laptop, ON BATTERY (plug in and run again for fair numbers)" }

Write-Host ""
Write-Host "Stage 1 sequential benchmark - $($cpu.Name.Trim())" -ForegroundColor Cyan
Write-Host "Keep the charger plugged in, close other programs and do not use the computer until it finishes."
Write-Host "Settings: sizes $Sizes, steps $Steps, repeats $Repeats, seed $Seed"
Write-Host ""

New-Item -ItemType Directory -Force results | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmm"
$safeName = ($Name -replace "[^A-Za-z0-9_-]", "")
if (-not $safeName) { $safeName = "member" }
$csvPath = "results\S1_${safeName}_${env:COMPUTERNAME}_$stamp.csv"
$rows = @("variant,grain,schedule,threads,n,steps,seed,repeat,seconds,pe_last,energy_drift")
$summary = @()
$prev = $null
$inv = [System.Globalization.CultureInfo]::InvariantCulture
foreach ($n in ($Sizes -split "," | Where-Object { $_ })) {
    Write-Host "  running n = $n ..." -NoNewline
    $lines = @(& $exe --csv --n $n --steps $Steps --repeats $Repeats --seed $Seed)
    if ($LASTEXITCODE) { throw "run failed for n = $n" }
    $rows += $lines
    $t = @($lines | ForEach-Object { [double](($_ -split ",")[8]) } | Sort-Object)
    $med = $t[[int][math]::Floor($t.Count / 2)]
    $growth = ""
    if ($prev) { $growth = [string]::Format($inv, "{0:F2}x", $med / $prev) }
    $summary += [string]::Format($inv, "{0,-7} {1,10:F4} {2,10:F4} {3,10:F4} {4,8}", $n, $med, $t[0], $t[-1], $growth)
    $prev = $med
    Write-Host ([string]::Format($inv, " median {0:F4} s", $med))
}
$rows | Set-Content -Encoding ascii $csvPath

$block = @(
    "===== Stage 1 result (copy from here) =====",
    "Member       : $Name",
    "Machine      : $env:COMPUTERNAME",
    "OS           : $($os.Caption.Trim()) $($os.Version) ($arch)",
    "CPU          : $($cpu.Name.Trim())",
    "Cores        : $cores physical / $logical logical",
    "Max clock    : $($cpu.MaxClockSpeed) MHz",
    "Cache        : L2 $($cpu.L2CacheSize) KB / L3 $($cpu.L3CacheSize) KB",
    "RAM          : $ramGB GB",
    "Power        : $power",
    "Binary       : $binaryNote, $compiler",
    "Settings     : steps=$Steps repeats=$Repeats seed=$Seed (time = median)",
    "",
    "N         median_s      min_s      max_s   growth",
    $summary,
    "",
    "CSV file     : $csvPath",
    "===== (copy until here) ====="
) | ForEach-Object { $_ }

Write-Host ""
$block | ForEach-Object { Write-Host $_ }
try { ($block -join "`r`n") | Set-Clipboard; Write-Host ""; Write-Host "The block above is already copied. Paste it into the Device form (Stage 1 result box)." -ForegroundColor Green }
catch { Write-Host "Select the block above and copy it by hand." }
Write-Host "Then upload $csvPath to the OneDrive folder 11-Project-Stage1/2-Benchmarks."
