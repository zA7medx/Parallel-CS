"""Stage 1 results: the report's tables and figures from the members' run-kit files.

    python 03-Project-Code/nbody-cpp/tools/stage1_results.py
    python tools/stage1_results.py --in DIR --specs DIR --out DIR --no-docx

Reads (defaults are the Stage 1 folders of the project):
  11-Project-Stage1/2-Benchmarks/S1_<Name>_<Machine>_<yyyymmdd-hhmm>.csv   raw runs from the run kit, one row per repeat
  S1_team-devices.csv in 2-Benchmarks or 3-CPU-Specs                       the hub's Team devices table (Download as CSV)
  11-Project-Stage1/3-CPU-Specs/*.txt                                      the text a member copied (run-kit block or Device form)
Writes to 11-Project-Stage1/4-Figures (existing files there with the same names are replaced):
  fig-time-vs-n.png        median time against N for every machine, log-log, with an N^2 guide line
  fig-time-by-member.png   time at the largest N, one bar per machine, coloured by architecture
  S1-results.md            every table, the checks and the list of files used
  S1-results.csv           one row per machine (for Excel)
  S1-results.json          the same data for 90-Assets/doc-kit
  S1-Results-Tables.docx   the report's tables 4.3, 5.1 and 5.2 and the figure, in the Assignment 1 style
                           (needs Node.js; built by 90-Assets/doc-kit/build.py s1-results)
Only the Python standard library and matplotlib are needed.
"""
import argparse
import csv
import datetime as dt
import json
import pathlib
import re
import shutil
import subprocess
import sys
from collections import Counter, defaultdict

HERE = pathlib.Path(__file__).resolve()
ROOT = HERE.parents[3]                      # project folder (tools -> nbody-cpp -> 03-Project-Code -> root)
STAGE1 = ROOT / "11-Project-Stage1 (due 2026-10-18)"
KIT_SETTINGS = {"steps": 50, "repeats": 5, "seed": 12345}
PE_TOL = 1e-9                               # relative difference of the final potential energy that counts as "different"
NAVY, TANGERINE, AQUA, MUTED = "#1B2559", "#FF6B1A", "#0FB5BA", "#6B7280"
LINE_COLOURS = [NAVY, TANGERINE, AQUA, "#7B61FF", "#E0457B", "#2E8B57", "#C9A227", "#5B8DEF", "#8C564B", "#00838F",
                "#D35400", "#6B7280"]
MARKERS = ["o", "s", "^", "D", "v", "P", "X", "<", ">", "h", "*", "p"]


# ---------- team list ----------
def load_team():
    """Member names in cover order, read from 90-Assets/doc-kit/team.js (the single place they are kept)."""
    team_js = ROOT / "90-Assets" / "doc-kit" / "team.js"
    if not team_js.exists():
        return []
    return re.findall(r'\{\s*name:\s*"([^"]+)"', team_js.read_text(encoding="utf-8"))


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def match_member(raw, team):
    """Map a name from a file ("AhmedAlnasser", "Habib", "Habib Al-Shaikh") to a team member; None if unsure."""
    s = norm(raw)
    if not s:
        return None
    hits = []
    for full in team:
        toks = [norm(t) for t in re.split(r"[\s]+", full) if norm(t)]
        if s == norm(full) or (len(toks[0]) >= 4 and s.startswith(toks[0])) or any(len(t) >= 5 and t in s for t in toks[1:]):
            hits.append(full)
    return hits[0] if len(hits) == 1 else None


def display(full):
    """AHMED ABDULLATIF ALNASSER -> Ahmed Abdullatif Alnasser; other names stay as written."""
    return full.title() if full.isupper() else full


# ---------- CPU and architecture labels ----------
def short_cpu(cpu):
    s = cpu or ""
    s = re.sub(r"\((R|TM|tm|r)\)", "", s)
    s = re.sub(r"\b\d+(th|nd|rd|st) Gen\b", "", s)
    s = re.sub(r"\bwith Radeon.*$|\bw/ Radeon.*$|@.*$|\bCPU\b|\bProcessor\b|\b\d+-Core\b", "", s, flags=re.I)
    s = s.replace("Intel Core", "Intel").replace("AMD Ryzen", "Ryzen").replace("Qualcomm Snapdragon", "Snapdragon")
    s = s.split(" - ")[0]   # "Snapdragon(R) X Plus - X1P64100 - Qualcomm(R) Oryon(TM) CPU" -> "Snapdragon X Plus"
    return re.sub(r"\s+", " ", s).strip() or "unknown CPU"


def clean_cpu(cpu):
    return re.sub(r"\s+", " ", re.sub(r"\((R|TM|tm|r)\)", "", cpu or "")).strip()


def short_os(os_text):
    """"Microsoft Windows 11 Home 10.0.22631 (AMD64)" -> "Windows 11 Home"; "macOS 14.5 (arm64)" -> "macOS 14.5"."""
    s = re.sub(r"^Microsoft\s+", "", os_text or "")
    s = re.sub(r"\s*\((amd64|x86_64|arm64|aarch64|x64|arm)\)\s*$", "", s, flags=re.I)
    s = re.sub(r"\s+10\.0\.\d+$", "", s)
    return s.strip()


def arch_of(*texts):
    t = " ".join(x for x in texts if x).lower()
    if re.search(r"arm64|aarch64|\barm\b|apple m\d|snapdragon|ampere|graviton|cobalt", t):
        return "Arm64"
    if re.search(r"amd64|x86[-_ ]?64|\bx64\b|intel|ryzen|epyc|xeon", t):
        return "x86-64"
    return ""


# ---------- readers ----------
def read_kit_csv(path, team):
    m = re.match(r"^S1_(.+?)_(.+)_(\d{8}-\d{4})\.csv$", path.name)
    if not m:
        return None
    raw_name, machine, stamp = m.groups()
    runs, pe, drift, settings = defaultdict(list), defaultdict(set), defaultdict(float), set()
    with path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            try:
                n = int(row["n"])
                runs[n].append(float(row["seconds"]))
                pe[n].add(float(row["pe_last"]))
                drift[n] = max(drift[n], abs(float(row["energy_drift"])))
                settings.add((row["variant"], int(row["threads"]), int(row["steps"]), int(row["seed"])))
            except (KeyError, ValueError):
                continue
    if not runs:
        return None
    member = match_member(raw_name, team)
    return {"member": member or raw_name, "matched": bool(member), "raw_name": raw_name, "machine": machine,
            "stamp": stamp, "runs": dict(runs), "pe": {n: sorted(v) for n, v in pe.items()}, "drift": dict(drift),
            "settings": sorted(settings), "files": [path.name], "spec": {}}


SPEC_KEYS = {  # label in the run-kit block or the Device form -> field
    "member": "name", "name": "name", "machine": "machine", "os": "os", "cpu": "cpu", "architecture": "arch",
    "cores": "cores_text", "cores / threads": "cores_threads", "core types": "core_types", "max clock": "clock",
    "cache": "cache", "ram": "ram", "power": "power", "binary": "binary", "settings": "settings",
}


def parse_spec_text(text):
    """Reads the run-kit block and/or the hub's Device form text (WhatsApp format: *Key:* value)."""
    spec, med = {}, {}
    for line in text.splitlines():
        line = line.strip().strip("`")
        m = re.match(r"^\*([^*]+?):\*\s*(.*)$", line) or re.match(r"^([A-Za-z][A-Za-z /]*?)\s*:\s*(.+)$", line)
        if m:
            key = SPEC_KEYS.get(m.group(1).strip().lower())
            if key and m.group(2).strip() and key not in spec:
                spec[key] = m.group(2).strip()
            continue
        m = re.match(r"^(\d{3,6})\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)", line)
        if m:
            med[int(m.group(1))] = tuple(float(x) for x in m.group(2, 3, 4))
    m = re.match(r"(\d+)\s*physical\s*/\s*(\d+)", spec.get("cores_text", ""))
    if m:
        spec["cores"], spec["threads"] = m.groups()
    m = re.match(r"(\d+|\?)\s*/\s*(\d+|\?)", spec.get("cores_threads", ""))
    if m:
        spec.setdefault("cores", m.group(1))
        spec.setdefault("threads", m.group(2))
    return spec, med


def read_devices_csv(path):
    out = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            spec = {"name": row.get("member", ""), "os": row.get("os", ""), "cpu": row.get("cpu", ""),
                    "arch": row.get("arch", ""), "cores": row.get("physical_cores", ""),
                    "threads": row.get("logical_processors", ""), "core_types": row.get("core_types", ""),
                    "clock": row.get("max_clock", ""), "cache": row.get("cache", ""), "ram": row.get("ram", "")}
            med = {}
            for k, v in row.items():
                m = re.match(r"median_s_n(\d+)$", k or "")
                if m and v:
                    try:
                        med[int(m.group(1))] = (float(v), None, None)
                    except ValueError:
                        pass
            out.append(({k: v for k, v in spec.items() if v}, med))
    return out


# ---------- merge ----------
def collect(in_dir, specs_dir, team):
    notes, ignored = [], []
    entries = {}
    for path in sorted(in_dir.glob("S1_*.csv")):
        if path.name.lower().startswith(("s1_team-devices", "s1-results")):
            continue
        e = read_kit_csv(path, team)
        if not e:
            ignored.append(f"{path.name} (not a run-kit result file)")
            continue
        key = (norm(e["member"]), e["machine"].lower())
        old = entries.get(key)
        if old:   # the same member ran again on the same machine: keep the newest file
            newer, older = (e, old) if e["stamp"] > old["stamp"] else (old, e)
            ignored.append(f"{older['files'][0]} (older run of {display(newer['member'])} on {newer['machine']})")
            e = newer
        elif not e["matched"]:
            notes.append(f"{path.name}: the name '{e['raw_name']}' does not match one team member; it is shown as written.")
        entries[key] = e

    specs = []   # (source file, spec fields, medians)
    folders = [specs_dir] + ([in_dir] if in_dir != specs_dir else [])
    for d in folders:
        if not d.exists():
            continue
        for path in sorted(d.glob("*.txt")):
            spec, med = parse_spec_text(path.read_text(encoding="utf-8", errors="replace"))
            if spec or med:
                specs.append((path.name, spec, med))
    for d in folders:   # the hub table after the copied texts, so a member's own text wins
        if d.exists():
            for path in sorted(d.glob("*team-devices*.csv")):
                specs += [(path.name, s, m) for s, m in read_devices_csv(path)]
    by_member = defaultdict(list)
    for e in entries.values():
        by_member[norm(e["member"])].append(e)
    for source, spec, med in specs:
        member = match_member(spec.get("name", ""), team) or match_member(pathlib.Path(source).stem.replace("Specs_", ""), team)
        if not member:
            if spec.get("name") or med:
                notes.append(f"{source}: could not tell which member this is; skipped.")
            continue
        cands = by_member.get(norm(member), [])
        machine = spec.get("machine", "").lower()
        if machine:   # the run-kit block names the machine: attach to that CSV, or it is another machine
            target = next((e for e in cands if e["machine"].lower() == machine), None)
            if target is None and not med and len(cands) == 1:
                target = cands[0]
        else:         # the hub table has no machine name
            target = cands[0] if cands else None
        if target is None:   # no CSV: use the medians from the copied block or the hub table
            if not med:
                continue
            target = {"member": member, "matched": True, "raw_name": member, "machine": spec.get("machine", "?"),
                      "stamp": "", "runs": {}, "pe": {}, "drift": {}, "settings": [], "files": [], "spec": {},
                      "block_medians": med}
            entries[(norm(member), target["machine"].lower())] = target
            by_member[norm(member)].append(target)
            notes.append(f"{display(member)}: no result CSV; the medians come from {source} (min and max "
                         + ("from the block" if any(v[1] is not None for v in med.values()) else "unknown") + ").")
        for k, v in spec.items():
            target["spec"].setdefault(k, v)
        target["files"].append(source)
    used = sorted({f for e in entries.values() for f in e["files"]})
    return list(entries.values()), notes, used, ignored


def summarise(entries, team):
    order = {norm(n): i for i, n in enumerate(team)}
    rows = []
    for e in entries:
        sp = e["spec"]
        stats = {}
        for n, ts in e["runs"].items():
            ts = sorted(ts)
            # the same median as the run kit prints (for an even count it takes the upper of the two middle values)
            stats[n] = {"median": ts[len(ts) // 2], "min": ts[0], "max": ts[-1], "repeats": len(ts)}
        for n, (md, mn, mx) in e.get("block_medians", {}).items():
            stats.setdefault(n, {"median": md, "min": mn, "max": mx, "repeats": None})
        steps = next((s[2] for s in e["settings"]), KIT_SETTINGS["steps"])
        arch = arch_of(sp.get("arch"), sp.get("os"), sp.get("cpu"), sp.get("binary"))
        rows.append({
            "member": display(e["member"]), "member_full": e["member"], "no": order.get(norm(e["member"]), 99) + 1,
            "machine": e["machine"], "cpu": clean_cpu(sp.get("cpu", "")), "cpu_short": short_cpu(sp.get("cpu", "")), "arch": arch,
            "cores": sp.get("cores", ""), "threads": sp.get("threads", ""), "core_types": sp.get("core_types", ""),
            "clock": sp.get("clock", ""), "cache": sp.get("cache", ""), "ram": sp.get("ram", ""), "os": short_os(sp.get("os", "")), "os_full": sp.get("os", ""),
            "power": sp.get("power", ""), "binary": sp.get("binary", ""), "steps": steps, "stats": stats,
            "pe": e["pe"], "drift": e["drift"], "settings": e["settings"], "files": e["files"],
        })
    rows.sort(key=lambda r: (r["no"], r["member"], r["machine"]))
    same = Counter(norm(r["member"]) for r in rows)
    for r in rows:
        r["label"] = r["member"] + (f" ({r['machine']})" if same[norm(r["member"])] > 1 else "")
        sizes = sorted(r["stats"])
        r["growth"] = {f"{a}->{b}": r["stats"][b]["median"] / r["stats"][a]["median"]
                       for a, b in zip(sizes, sizes[1:]) if b == 2 * a and r["stats"][a]["median"] > 0}
        big = sizes[-1] if sizes else None
        r["ns_per_pair"] = (r["stats"][big]["median"] / (r["steps"] * big * big) * 1e9) if big else None
        r["ns_per_pair_n"] = big
        spreads = [(s["max"] - s["min"]) / s["median"] * 100 for s in r["stats"].values()
                   if s["min"] is not None and s["max"] is not None and s["median"] > 0]
        r["spread_max_pct"] = max(spreads) if spreads else None
    return rows


def check(rows, team):
    warn = []
    for r in rows:
        who = r["label"]
        for variant, threads, steps, seed in r["settings"]:
            if variant != "seq" or threads != 1:
                warn.append(f"{who}: variant {variant} with {threads} threads; Stage 1 uses the sequential build.")
            if steps != KIT_SETTINGS["steps"] or seed != KIT_SETTINGS["seed"]:
                warn.append(f"{who}: steps={steps}, seed={seed}; the kit uses steps={KIT_SETTINGS['steps']}, "
                            f"seed={KIT_SETTINGS['seed']}. Do not mix these times with the others.")
        for n, s in sorted(r["stats"].items()):
            if s["repeats"] is not None and s["repeats"] != KIT_SETTINGS["repeats"]:
                warn.append(f"{who}: N={n} has {s['repeats']} repeats (the kit uses {KIT_SETTINGS['repeats']}).")
        if r["spread_max_pct"] is not None and r["spread_max_pct"] > 10:
            warn.append(f"{who}: repeats differ by up to {r['spread_max_pct']:.0f}% of the median. On battery, or other "
                        "programs running? Consider a re-run plugged in.")
        for k, g in r["growth"].items():
            if not 3.0 <= g <= 5.0:
                warn.append(f"{who}: time grew {g:.2f}x for N {k.replace('->', ' -> ')} (about 4x is expected). "
                            "Check for background load or a laptop slowing down when hot.")
        if emulated(r):
            warn.append(f"{who}: Windows on Arm ran the x64 prebuilt binary under emulation; its time is not a native Arm "
                        "time. Say so in the report, or build natively.")
    # every machine must compute the same physics: compare the final potential energy per N
    by_n = defaultdict(list)
    for r in rows:
        for n, vals in r["pe"].items():
            if len(vals) > 1:
                warn.append(f"{r['label']}: N={n} gave {len(vals)} different energies across repeats (it should be one).")
            by_n[n].append((r["label"], vals[0]))
    pe_ref, off = {}, defaultdict(list)
    for n, vals in sorted(by_n.items()):
        common = Counter(f"{v:.11e}" for _, v in vals).most_common(1)[0][0]
        ref = next(v for _, v in vals if f"{v:.11e}" == common)
        pe_ref[n] = ref
        for who, v in vals:
            rel = abs(v - ref) / abs(ref) if ref else abs(v)
            if rel > PE_TOL:
                off[who].append((n, rel))
    for who, items in off.items():
        warn.append(f"{who}: the final potential energy differs from the other machines at N = "
                    + ", ".join(str(n) for n, _ in items) + f" (relative difference up to {max(r for _, r in items):.1e}; "
                    f"identical runs agree to about 1e-12). Different settings or a modified program: do not use "
                    "these times until it is explained.")
    no_spec = [r["label"] for r in rows if not r["arch"]]
    if no_spec:
        warn.append("No CPU specification yet for: " + ", ".join(no_spec) + ". Put the text they copied in 3-CPU-Specs "
                    "(Specs_<Name>.txt), or download the hub's Team devices CSV into 2-Benchmarks.")
    missing = [display(m) for m in team if norm(m) not in {norm(r["member_full"]) for r in rows}]
    pe_info = {"machines": sorted(r["label"] for r in rows if r["pe"]), "differ": sorted(off)}
    return warn, missing, pe_info


# ---------- figures ----------
def emulated(r):
    return r["arch"] == "Arm64" and "windows" in r["os"].lower() and "prebuilt" in r["binary"].lower()


def arch_tag(r):
    return " (Arm64, x64 binary emulated)" if emulated(r) else (" (Arm64)" if r["arch"] == "Arm64" else "")


def setup_matplotlib():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    names = {f.name for f in font_manager.fontManager.ttflist}
    plt.rcParams.update({
        "font.family": "Segoe UI" if "Segoe UI" in names else "DejaVu Sans", "font.size": 9,
        "axes.edgecolor": "#C9CEDB", "axes.labelcolor": "#1F2433", "axes.titleweight": "bold", "axes.titlesize": 10.5,
        "axes.titlecolor": NAVY, "xtick.color": "#3A4055", "ytick.color": "#3A4055", "axes.spines.top": False,
        "axes.spines.right": False, "legend.frameon": False, "savefig.dpi": 220, "savefig.bbox": "tight",
    })
    return plt


def fig_time_vs_n(rows, out, plt):
    from matplotlib.ticker import FixedLocator, FuncFormatter, NullLocator
    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    sizes = sorted({n for r in rows for n in r["stats"]})
    for i, r in enumerate(rows):
        ns = sorted(r["stats"])
        md = [r["stats"][n]["median"] for n in ns]
        lo = [md[k] - (r["stats"][n]["min"] if r["stats"][n]["min"] is not None else md[k]) for k, n in enumerate(ns)]
        hi = [(r["stats"][n]["max"] if r["stats"][n]["max"] is not None else md[k]) - md[k] for k, n in enumerate(ns)]
        ax.errorbar(ns, md, yerr=[lo, hi], color=LINE_COLOURS[i % len(LINE_COLOURS)], marker=MARKERS[i % len(MARKERS)],
                    markersize=4.5, linewidth=1.4, elinewidth=0.8, capsize=2,
                    label=f"{r['label']}: {r['cpu_short']}" + arch_tag(r))
    if len(sizes) >= 2:   # dashed guide: time proportional to N^2 through the fastest machine's first point
        n0 = sizes[0]
        t0 = min(r["stats"][n0]["median"] for r in rows if n0 in r["stats"])
        ax.plot(sizes, [t0 * (n / n0) ** 2 for n in sizes], linestyle="--", color="#9AA1B2", linewidth=1,
                label="Guide: time grows as N² (slope 2)")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.xaxis.set_major_locator(FixedLocator(sizes))
    ax.xaxis.set_minor_locator(NullLocator())
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{int(v):,}"))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
    ax.set_xlabel("Number of bodies N (log scale)")
    ax.set_ylabel("Median time of the step loop, seconds (log scale)")
    steps = rows[0]["steps"] if rows else KIT_SETTINGS["steps"]
    ax.set_title(f"Sequential time against N ({steps} steps, median of {KIT_SETTINGS['repeats']} runs; bars = min to max)",
                 loc="left")
    ax.grid(True, which="major", color="#E6E9F0", linewidth=0.7)
    ncol = 1 if len(rows) <= 5 else 2
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=ncol, fontsize=7.6, handlelength=2.2)
    fig.savefig(out)
    plt.close(fig)


def fig_by_member(rows, out, plt):
    sizes = sorted({n for r in rows for n in r["stats"]})
    common = [n for n in sizes if all(n in r["stats"] for r in rows)]
    n = common[-1] if common else sizes[-1]
    data = sorted([r for r in rows if n in r["stats"]], key=lambda r: r["stats"][n]["median"], reverse=True)
    fig, ax = plt.subplots(figsize=(7.2, 0.42 * len(data) + 1.3))
    colours = {"x86-64": NAVY, "Arm64": TANGERINE}
    vals = [r["stats"][n]["median"] for r in data]
    ax.barh([f"{r['label']}  ·  {r['cpu_short']}" + (" (x64 emulated)" if emulated(r) else "") for r in data], vals,
            color=[colours.get(r["arch"], MUTED) for r in data], height=0.62)
    for y, v in enumerate(vals):
        ax.text(v, y, f"  {v:.3f} s", va="center", fontsize=8, color="#1F2433")
    ax.set_xlim(0, max(vals) * 1.18 if vals else 1)
    ax.set_xlabel(f"Median time of the step loop at N = {n:,}, seconds")
    ax.set_title(f"Sequential time on each machine at N = {n:,} (shorter is faster)", loc="left")
    from matplotlib.patches import Patch
    present = [a for a in ("x86-64", "Arm64") if any(r["arch"] == a for r in data)]
    handles = [Patch(color=colours[a], label=a) for a in present]
    if any(not r["arch"] for r in data):
        handles.append(Patch(color=MUTED, label="architecture unknown"))
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.13 - 0.35 / max(len(data), 1)),
              ncol=len(handles), fontsize=8)
    ax.grid(True, axis="x", color="#E6E9F0", linewidth=0.7)
    ax.set_axisbelow(True)
    fig.savefig(out)
    plt.close(fig)
    return n


# ---------- text outputs ----------
def spread_by_n(r):
    return {str(n): (s["max"] - s["min"]) / s["median"] * 100 for n, s in r["stats"].items()
            if s["min"] is not None and s["max"] is not None and s["median"] > 0}


def fmt(v, d=4):
    return "" if v is None else f"{v:.{d}f}"


def md_table(head, body, text_cols=2):
    out = ["| " + " | ".join(head) + " |", "|" + "|".join("---" if i < text_cols else "---:" for i in range(len(head))) + "|"]
    out += ["| " + " | ".join(str(c) for c in row) + " |" for row in body]
    return "\n".join(out)


def write_outputs(rows, warn, missing, notes, used, ignored, out_dir, figs, bar_n, pe_info):
    sizes = sorted({n for r in rows for n in r["stats"]})
    pairs = [f"{a}->{2 * a}" for a in sizes if 2 * a in sizes]
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    spec_rows = [[r["no"] if r["no"] < 100 else "", r["label"], r["cpu"] or "?", r["arch"] or "?",
                  f"{r['cores'] or '?'} / {r['threads'] or '?'}", r["clock"], r["cache"], r["ram"], r["os"]] for r in rows]
    time_rows = [[r["no"] if r["no"] < 100 else "", r["label"], r["cpu_short"]]
                 + [fmt(r["stats"][n]["median"]) if n in r["stats"] else "–" for n in sizes] for r in rows]
    growth_rows = [[r["no"] if r["no"] < 100 else "", r["label"]]
                   + [f"{r['growth'][k]:.2f}×" if k in r["growth"] else "–" for k in pairs]
                   + [fmt(r["ns_per_pair"], 2)] for r in rows]
    spread_rows = [[r["no"] if r["no"] < 100 else "", r["label"]]
                   + [(f"{(r['stats'][n]['max'] - r['stats'][n]['min']) / r['stats'][n]['median'] * 100:.1f}%"
                       if n in r["stats"] and r["stats"][n]["min"] is not None else "–") for n in sizes] for r in rows]
    ns_n = max((r["ns_per_pair_n"] or 0) for r in rows) if rows else 0
    lines = [
        "# Stage 1 results (generated)", "",
        f"Generated {now} by `03-Project-Code/nbody-cpp/tools/stage1_results.py` from {len(rows)} machine(s). "
        "Do not edit this file: add or fix the input files and run the script again.", "",
        "## CPU specification of each machine (report Table 4.3)", "",
        md_table(["No.", "Member", "CPU model", "Arch.", "Cores / threads", "Clock (OS)", "Cache", "RAM", "OS"], spec_rows,
                 text_cols=9), "",
        f"## Sequential time in seconds, median of {KIT_SETTINGS['repeats']} runs (report Table 5.1)", "",
        md_table(["No.", "Member", "CPU"] + [f"N = {n}" for n in sizes], time_rows, text_cols=3), "",
        "## Growth when N doubles, and time per pair (report Table 5.2)", "",
        md_table(["No.", "Member"] + [k.replace("->", " → ") for k in pairs] + [f"ns per pair (N = {ns_n})"], growth_rows), "",
        "Time per pair = median time / (steps × N²). About 4× per doubling means the time grows with N².", "",
        "## Spread of the repeats, (max − min) / median (report Section 5.3)", "",
        md_table(["No.", "Member"] + [f"N = {n}" for n in sizes], spread_rows), "",
        "## Figures", "",
    ]
    lines += [f"- `{f}`" for f in figs]
    if bar_n:
        lines.append(f"  (the bar chart uses N = {bar_n}, the largest size every machine ran)")
    lines += ["", "## Checks", ""]
    lines += [f"- {w}" for w in warn] or ["- No problems found: same settings everywhere, the same energies on every "
                                          "machine, growth between 3× and 5×, spread under 10%."]
    lines += ["", "## Members without a result yet", ""]
    lines += [", ".join(missing) if missing else "None: every member is in."]
    if notes:
        lines += ["", "## Notes", ""] + [f"- {n}" for n in notes]
    lines += ["", "## Files used", ""] + [f"- `{u}`" for u in used]
    if ignored:
        lines += ["", "## Files ignored", ""] + [f"- `{i}`" for i in ignored]
    (out_dir / "S1-results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    with (out_dir / "S1-results.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["no", "member", "machine", "cpu", "arch", "physical_cores", "logical_processors", "max_clock", "cache",
                    "ram", "os", "steps"] + [f"median_s_n{n}" for n in sizes] + [f"min_s_n{n}" for n in sizes]
                   + [f"max_s_n{n}" for n in sizes] + [f"growth_{k}" for k in pairs]
                   + ["ns_per_pair_largest_n", "max_spread_pct", "source_files"])
        for r in rows:
            g = lambda n, k: fmt(r["stats"][n][k], 6) if n in r["stats"] and r["stats"][n][k] is not None else ""
            w.writerow([r["no"] if r["no"] < 100 else "", r["label"], r["machine"], r["cpu"], r["arch"], r["cores"],
                        r["threads"], r["clock"], r["cache"], r["ram"], r["os"], r["steps"]]
                       + [g(n, "median") for n in sizes] + [g(n, "min") for n in sizes] + [g(n, "max") for n in sizes]
                       + [f"{r['growth'][k]:.3f}" if k in r["growth"] else "" for k in pairs]
                       + [fmt(r["ns_per_pair"], 3), fmt(r["spread_max_pct"], 1), "; ".join(r["files"])])

    data = {
        "generated": now, "steps": rows[0]["steps"] if rows else KIT_SETTINGS["steps"], "repeats": KIT_SETTINGS["repeats"],
        "seed": KIT_SETTINGS["seed"], "sizes": sizes, "pairs": pairs, "ns_n": ns_n,
        "rows": [{"no": r["no"] if r["no"] < 100 else "", "member": r["label"], "cpu": r["cpu"] or "?",
                  "cpu_short": r["cpu_short"], "arch": r["arch"] or "?",
                  "cores_threads": f"{r['cores'] or '?'} / {r['threads'] or '?'}", "clock": r["clock"],
                  "cache": r["cache"], "ram": r["ram"], "os": r["os"],
                  "medians": {str(n): fmt(r["stats"][n]["median"]) for n in r["stats"]},
                  "growth": {k: f"{v:.2f}×" for k, v in r["growth"].items()}, "ns_per_pair": fmt(r["ns_per_pair"], 2),
                  "median_values": {str(n): s["median"] for n, s in r["stats"].items()},
                  "growth_values": r["growth"], "ns_per_pair_value": r["ns_per_pair"],
                  "spread_max_pct": r["spread_max_pct"], "spread_by_n": spread_by_n(r),
                  "emulated": emulated(r), "power": r["power"], "binary": r["binary"], "has_csv": bool(r["pe"])}
                 for r in rows],
        "figures": [str((out_dir / f).resolve()) for f in figs], "bar_n": bar_n, "warnings": warn, "missing": missing,
        "pe_check": pe_info,
    }
    (out_dir / "S1-results.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def build_docx(out_dir):
    build_py = ROOT / "90-Assets" / "doc-kit" / "build.py"
    if not build_py.exists() or not shutil.which("node"):
        print("Word tables skipped: needs Node.js and 90-Assets/doc-kit (run with --no-docx to hide this message).")
        return
    res = subprocess.run([sys.executable, str(build_py), "s1-results", "--data", str(out_dir / "S1-results.json"),
                          "--out", str(out_dir / "S1-Results-Tables.docx")])
    if res.returncode:
        print("Word tables were not built (see the message above); the PNG, MD and CSV files are fine.")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--in", dest="in_dir", default=str(STAGE1 / "2-Benchmarks"), help="folder with the S1_*.csv files")
    ap.add_argument("--specs", default=str(STAGE1 / "3-CPU-Specs"), help="folder with the copied spec texts")
    ap.add_argument("--out", default=str(STAGE1 / "4-Figures"), help="where the figures and tables go")
    ap.add_argument("--no-docx", action="store_true", help="skip the Word tables")
    a = ap.parse_args()
    in_dir, specs_dir, out_dir = pathlib.Path(a.in_dir), pathlib.Path(a.specs), pathlib.Path(a.out)
    team = load_team()
    entries, notes, used, ignored = collect(in_dir, specs_dir, team)
    if not entries:
        raise SystemExit(f"No results found. Put the members' S1_*.csv files in {in_dir} "
                         f"(and their copied text in {specs_dir}), then run this again.")
    rows = summarise(entries, team)
    warn, missing, pe_info = check(rows, team)
    out_dir.mkdir(parents=True, exist_ok=True)
    plt = setup_matplotlib()
    fig_time_vs_n(rows, out_dir / "fig-time-vs-n.png", plt)
    bar_n = fig_by_member(rows, out_dir / "fig-time-by-member.png", plt)
    figs = ["fig-time-vs-n.png", "fig-time-by-member.png"]
    write_outputs(rows, warn, missing, notes, used, ignored, out_dir, figs, bar_n, pe_info)
    print(f"{len(rows)} machine(s): " + ", ".join(r["label"] for r in rows))
    print(f"missing: {', '.join(missing) if missing else 'nobody'}")
    print(f"{len(warn)} check(s) to look at" + (": see S1-results.md" if warn else ""))
    for w in warn[:8]:
        print("  - " + w)
    print(f"wrote {', '.join(figs)}, S1-results.md, S1-results.csv, S1-results.json in {out_dir}")
    if not a.no_docx:
        build_docx(out_dir)


if __name__ == "__main__":
    main()
