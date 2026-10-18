#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <string>
#include <vector>

#ifdef _OPENMP
#include <omp.h>
#endif

#include "nbody.hpp"

namespace {

struct Options {
    std::size_t n = 2000;
    int steps = 100;
    std::uint64_t seed = 12345;
    nb::Variant variant = nb::Variant::Seq;
    nb::Grain grain = nb::Grain::Body;
    int threads = 0;            // 0 = leave OpenMP default
    std::string schedule = "static";
    int chunk = 0;
    int repeats = 1;
    bool check = false;
    double tol = -1.0;
    bool csv = false;
    bool csv_header = false;
    bool info = false;
    std::string snapshot;
    int snapshot_every = 10;
    nb::Params params;
};

const char* variant_name(nb::Variant v) {
    switch (v) {
        case nb::Variant::Seq: return "seq";
        case nb::Variant::Unsafe: return "unsafe";
        case nb::Variant::Critical: return "critical";
        case nb::Variant::Atomic: return "atomic";
        case nb::Variant::Reduction: return "reduction";
    }
    return "?";
}

void usage() {
    std::puts(
        "usage: nbody [options]\n"
        "  --n N               number of bodies (default 2000)\n"
        "  --steps S           time steps (default 100)\n"
        "  --seed K            seed of the input generator (default 12345)\n"
        "  --variant V         seq | unsafe | critical | atomic | reduction (default seq)\n"
        "  --grain G           body | pair: how often the shared total is updated (default body)\n"
        "  --threads T         number of OpenMP threads (OpenMP build only)\n"
        "  --schedule S        static | dynamic | guided (default static), --chunk C\n"
        "  --repeats R         repeat the timed run R times from the same input (default 1)\n"
        "  --check --tol X     compare with the sequential result; X is chosen by the group\n"
        "  --csv / --csv-header   machine-readable output\n"
        "  --snapshot FILE [--snapshot-every K]   write positions for an animation (timing not valid)\n"
        "  --dt X --eps X      time step and softening length\n"
        "  --info              print compiler and OpenMP information and exit");
}

bool need(int i, int argc, const char* name) {
    if (i + 1 >= argc) { std::fprintf(stderr, "missing value for %s\n", name); return false; }
    return true;
}

bool parse(int argc, char** argv, Options& o) {
    for (int i = 1; i < argc; ++i) {
        const std::string a = argv[i];
        auto val = [&]() -> const char* { return argv[++i]; };
        if (a == "--help" || a == "-h") { usage(); std::exit(0); }
        else if (a == "--check") o.check = true;
        else if (a == "--csv") o.csv = true;
        else if (a == "--csv-header") { o.csv = true; o.csv_header = true; }
        else if (a == "--info") o.info = true;
        else if (!need(i, argc, a.c_str())) return false;
        else if (a == "--n") o.n = std::strtoull(val(), nullptr, 10);
        else if (a == "--steps") o.steps = std::atoi(val());
        else if (a == "--seed") o.seed = std::strtoull(val(), nullptr, 10);
        else if (a == "--threads") o.threads = std::atoi(val());
        else if (a == "--chunk") o.chunk = std::atoi(val());
        else if (a == "--repeats") o.repeats = std::atoi(val());
        else if (a == "--tol") o.tol = std::atof(val());
        else if (a == "--dt") o.params.dt = std::atof(val());
        else if (a == "--eps") o.params.eps = std::atof(val());
        else if (a == "--snapshot") o.snapshot = val();
        else if (a == "--snapshot-every") o.snapshot_every = std::atoi(val());
        else if (a == "--schedule") o.schedule = val();
        else if (a == "--grain") {
            const std::string g = val();
            if (g == "body") o.grain = nb::Grain::Body;
            else if (g == "pair") o.grain = nb::Grain::Pair;
            else { std::fprintf(stderr, "unknown grain: %s\n", g.c_str()); return false; }
        } else if (a == "--variant") {
            const std::string v = val();
            if (v == "seq") o.variant = nb::Variant::Seq;
            else if (v == "unsafe") o.variant = nb::Variant::Unsafe;
            else if (v == "critical") o.variant = nb::Variant::Critical;
            else if (v == "atomic") o.variant = nb::Variant::Atomic;
            else if (v == "reduction") o.variant = nb::Variant::Reduction;
            else { std::fprintf(stderr, "unknown variant: %s\n", v.c_str()); return false; }
        } else { std::fprintf(stderr, "unknown option: %s\n", a.c_str()); return false; }
    }
    if (o.n < 2 || o.steps < 1 || o.repeats < 1) { std::fprintf(stderr, "n >= 2, steps >= 1, repeats >= 1 required\n"); return false; }
    if (o.check && o.tol <= 0) { std::fprintf(stderr, "--check needs --tol X (X > 0). The group fixes the tolerance before measuring.\n"); return false; }
    return true;
}

void print_info() {
#if defined(__clang__)
    std::printf("compiler: clang %s\n", __clang_version__);
#elif defined(__GNUC__)
    std::printf("compiler: gcc/g++ %s\n", __VERSION__);
#else
    std::printf("compiler: unknown\n");
#endif
    std::printf("c++ standard: %ld\n", static_cast<long>(__cplusplus));
    std::printf("openmp: %s\n", nb::openmp_enabled() ? "enabled" : "not enabled (sequential build)");
#ifdef _OPENMP
    std::printf("openmp version macro: %d\n", _OPENMP);
    std::printf("omp max threads: %d, processors seen by OpenMP: %d\n", omp_get_max_threads(), omp_get_num_procs());
#endif
}

void set_schedule(const Options& o) {
#ifdef _OPENMP
    omp_sched_t k = omp_sched_static;
    if (o.schedule == "dynamic") k = omp_sched_dynamic;
    else if (o.schedule == "guided") k = omp_sched_guided;
    omp_set_schedule(k, o.chunk);
    if (o.threads > 0) omp_set_num_threads(o.threads);
#else
    (void)o;
#endif
}

int active_threads(const Options& o) {
#ifdef _OPENMP
    return o.threads > 0 ? o.threads : omp_get_max_threads();
#else
    (void)o;
    return 1;
#endif
}

struct Result { double seconds; double pe_last; };

Result run_once(const nb::System& init, const Options& o, nb::Variant v, nb::System& out, bool snapshots) {
    out = init;
    nb::prepare(out, o.params);
    std::ofstream snap;
    if (snapshots) snap.open(o.snapshot);
    double pe = 0.0;
    const auto t0 = std::chrono::steady_clock::now();
    for (int s = 0; s < o.steps; ++s) {
        pe = nb::step(out, o.params, v, o.grain);
        if (snapshots && s % o.snapshot_every == 0)
            for (std::size_t i = 0; i < out.n; ++i) snap << s << ',' << i << ',' << out.x[i] << ',' << out.y[i] << ',' << out.z[i] << '\n';
    }
    const auto t1 = std::chrono::steady_clock::now();
    return {std::chrono::duration<double>(t1 - t0).count(), pe};
}

}  // namespace

int main(int argc, char** argv) {
    Options o;
    if (!parse(argc, argv, o)) { usage(); return 2; }
    if (o.info) { print_info(); return 0; }
    if (o.variant != nb::Variant::Seq && !nb::openmp_enabled()) {
        std::fprintf(stderr, "variant '%s' needs the OpenMP build (build/nbody-omp)\n", variant_name(o.variant));
        return 2;
    }
    set_schedule(o);

    nb::System init;
    nb::init_random(init, o.n, o.seed);
    nb::System ref_start = init;
    nb::prepare(ref_start, o.params);
    const double e0 = nb::kinetic_energy(ref_start) + nb::potential_energy_reference(ref_start, o.params);

    if (o.csv_header)
        std::puts("variant,grain,schedule,threads,n,steps,seed,repeat,seconds,pe_last,energy_drift");
    const bool snapshots = !o.snapshot.empty();
    if (snapshots && !o.csv) std::puts("note: snapshot output is on, so the time below is NOT valid for benchmarking");

    nb::System result;
    std::vector<double> times;
    Result last{0, 0};
    for (int r = 1; r <= o.repeats; ++r) {
        last = run_once(init, o, o.variant, result, snapshots && r == 1);
        times.push_back(last.seconds);
        const double e_end = nb::kinetic_energy(result) + nb::potential_energy_reference(result, o.params);
        const double drift = (e_end - e0) / std::fabs(e0);
        if (o.csv)
            std::printf("%s,%s,%s,%d,%zu,%d,%llu,%d,%.6f,%.12e,%.6e\n", variant_name(o.variant),
                        o.grain == nb::Grain::Body ? "body" : "pair", o.schedule.c_str(), active_threads(o), o.n, o.steps,
                        static_cast<unsigned long long>(o.seed), r, last.seconds, last.pe_last, drift);
        else
            std::printf("run %d: %.4f s  (variant %s, threads %d, n %zu, steps %d)  accumulated PE %.10e  energy drift %.3e\n", r,
                        last.seconds, variant_name(o.variant), active_threads(o), o.n, o.steps, last.pe_last, drift);
    }
    if (!o.csv && o.repeats > 1) {
        std::sort(times.begin(), times.end());
        std::printf("median of %d runs: %.4f s  (min %.4f, max %.4f)\n", o.repeats, times[times.size() / 2], times.front(), times.back());
    }

    int exit_code = 0;
    if (o.check) {
        nb::System ref;
        const Result rr = run_once(init, o, nb::Variant::Seq, ref, false);
        double max_dpos = 0.0;
        for (std::size_t i = 0; i < o.n; ++i) {
            max_dpos = std::max({max_dpos, std::fabs(result.x[i] - ref.x[i]), std::fabs(result.y[i] - ref.y[i]), std::fabs(result.z[i] - ref.z[i])});
        }
        const double rel_pe = std::fabs(last.pe_last - rr.pe_last) / std::fabs(rr.pe_last);
        const bool ok = max_dpos <= o.tol && rel_pe <= o.tol;
        std::printf("check vs sequential: max |position difference| = %.3e, relative error of accumulated PE = %.3e, tolerance %.3e -> %s\n",
                    max_dpos, rel_pe, o.tol, ok ? "PASS" : "FAIL");
        if (!ok) exit_code = 1;
    }
    return exit_code;
}
