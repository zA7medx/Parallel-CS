#!/usr/bin/env python3
"""Prints the CPU specification of this machine as a table row for the Stage 1 report.
Standard library only. Works on Windows, Linux and macOS.
Check the numbers by eye: hybrid CPUs (Intel P-cores + E-cores, Apple chips) need a note on the core types."""
import json
import os
import platform
import re
import shutil
import subprocess
import sys


def run(cmd, shell=False):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, shell=shell, timeout=30).stdout.strip()
    except Exception:
        return ""


def windows():
    ps = ("Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors,"
          "MaxClockSpeed,L2CacheSize,L3CacheSize | ConvertTo-Json -Compress")
    raw = run(["powershell", "-NoProfile", "-Command", ps])
    cpus = json.loads(raw) if raw else []
    if isinstance(cpus, dict):
        cpus = [cpus]
    ram = run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory"])
    c = cpus[0] if cpus else {}
    return {
        "cpu": (c.get("Name") or "").strip(),
        "sockets": len(cpus) or 1,
        "physical_cores": sum(int(x.get("NumberOfCores", 0)) for x in cpus),
        "logical": sum(int(x.get("NumberOfLogicalProcessors", 0)) for x in cpus),
        "max_mhz": c.get("MaxClockSpeed"),
        "l2": f"{c.get('L2CacheSize')} KB" if c.get("L2CacheSize") else "",
        "l3": f"{c.get('L3CacheSize')} KB" if c.get("L3CacheSize") else "",
        "ram_gb": round(int(ram) / 2**30, 1) if ram.isdigit() else "",
    }


def linux():
    info = {}
    for line in run(["lscpu"]).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            info[k.strip()] = v.strip()
    mem = ""
    try:
        with open("/proc/meminfo") as f:
            m = re.search(r"MemTotal:\s+(\d+) kB", f.read())
            mem = round(int(m.group(1)) / 2**20, 1) if m else ""
    except OSError:
        pass
    sockets = int(info.get("Socket(s)", "1") or 1)
    cores_per = int(info.get("Core(s) per socket", "0") or 0)
    threads = int(info.get("Thread(s) per core", "1") or 1)
    return {
        "cpu": info.get("Model name", platform.processor()),
        "sockets": sockets,
        "physical_cores": sockets * cores_per,
        "logical": sockets * cores_per * threads,
        "max_mhz": info.get("CPU max MHz", ""),
        "l2": info.get("L2 cache", ""),
        "l3": info.get("L3 cache", ""),
        "ram_gb": mem,
    }


def mac():
    def s(k):
        return run(["sysctl", "-n", k])
    ram = s("hw.memsize")
    return {
        "cpu": s("machdep.cpu.brand_string"),
        "sockets": 1,
        "physical_cores": s("hw.physicalcpu"),
        "logical": s("hw.logicalcpu"),
        "max_mhz": "",
        "l2": s("hw.l2cachesize"),
        "l3": s("hw.l3cachesize"),
        "ram_gb": round(int(ram) / 2**30, 1) if ram.isdigit() else "",
    }


def compiler():
    for cxx in (os.environ.get("CXX"), "g++", "clang++"):
        if cxx and shutil.which(cxx):
            return run([cxx, "--version"]).splitlines()[0]
    return "not found"


def main():
    sysname = platform.system()
    d = windows() if sysname == "Windows" else mac() if sysname == "Darwin" else linux()
    d.update({"machine": platform.node(), "os": f"{platform.system()} {platform.release()}", "arch": platform.machine(),
              "compiler": compiler()})
    print("CPU specification (copy into the report table; check it by eye)")
    for k in ("machine", "os", "arch", "cpu", "sockets", "physical_cores", "logical", "max_mhz", "l2", "l3", "ram_gb", "compiler"):
        print(f"  {k:15s}: {d.get(k, '')}")
    print("\nMarkdown row:")
    print("| machine | CPU | architecture | physical cores | logical threads | RAM (GB) | OS | compiler |")
    print("|---|---|---|---|---|---|---|---|")
    print(f"| {d['machine']} | {d['cpu']} | {d['arch']} | {d['physical_cores']} | {d['logical']} | {d['ram_gb']} | {d['os']} | {d['compiler']} |")
    print("\nNote for the report: if the CPU has performance and efficiency cores, or SMT / Hyper-Threading,"
          "\nwrite how many threads are real cores. 8 logical threads are not always 8 cores.")


if __name__ == "__main__":
    sys.exit(main())
