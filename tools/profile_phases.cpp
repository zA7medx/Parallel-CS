// Stage 1 profile: how much of one time step is the O(N^2) force loop, and how much is the rest.
// Separate tool: it links the same src/nbody.cpp but does not change the program the team benchmarks.
//
// Build and run (from the nbody-cpp folder):
//   g++ -std=c++17 -O2 -Wno-unknown-pragmas -static tools/profile_phases.cpp src/nbody.cpp -Isrc -o build/profile-phases
//   build/profile-phases                     (defaults: sizes 1000,2000,4000,8000, 50 steps, 5 repeats, seed 12345)
//   build/profile-phases --sizes 1000,2000 --steps 20 --repeats 3
//
// Method, each value the median of the repeats, all on the same seeded input:
//   step   = S calls of nb::step (the loop the benchmark times)
//   force  = S calls of nb::compute_accel (the O(N^2) pair loop alone)
//   linear = S passes of the three O(N) loops of nb::step (kick, drift, kick), copied below so they can be timed alone
// force% and linear% are shares of force + linear (the two parts of a step, timed separately);
// sum/step = (force + linear) / step is a check that the two parts account for the step (1.00 up to the noise);
// spread% = (max - min) / median of the step repeats (the run-to-run noise).
#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>

#include "nbody.hpp"

namespace {

using Clock = std::chrono::steady_clock;

double seconds_since(Clock::time_point t0) { return std::chrono::duration<double>(Clock::now() - t0).count(); }

double median(std::vector<double> v) {
    std::sort(v.begin(), v.end());
    return v[v.size() / 2];
}

// The same three O(N) loops as nb::step in src/nbody.cpp (keep them in step if that function changes).
void linear_loops(nb::System& s, const nb::Params& p) {
    const std::size_t n = s.n;
    for (std::size_t i = 0; i < n; ++i) {  // kick (half step)
        s.vx[i] += 0.5 * p.dt * s.ax[i]; s.vy[i] += 0.5 * p.dt * s.ay[i]; s.vz[i] += 0.5 * p.dt * s.az[i];
    }
    for (std::size_t i = 0; i < n; ++i) {  // drift
        s.x[i] += p.dt * s.vx[i]; s.y[i] += p.dt * s.vy[i]; s.z[i] += p.dt * s.vz[i];
    }
    for (std::size_t i = 0; i < n; ++i) {  // kick (second half step)
        s.vx[i] += 0.5 * p.dt * s.ax[i]; s.vy[i] += 0.5 * p.dt * s.ay[i]; s.vz[i] += 0.5 * p.dt * s.az[i];
    }
}

std::vector<std::size_t> parse_sizes(const std::string& s) {
    std::vector<std::size_t> out;
    std::size_t pos = 0;
    while (pos < s.size()) {
        const std::size_t comma = s.find(',', pos);
        const std::string tok = s.substr(pos, comma == std::string::npos ? std::string::npos : comma - pos);
        if (!tok.empty()) out.push_back(std::strtoull(tok.c_str(), nullptr, 10));
        if (comma == std::string::npos) break;
        pos = comma + 1;
    }
    return out;
}

}  // namespace

int main(int argc, char** argv) {
    std::string sizes = "1000,2000,4000,8000";
    int steps = 50, repeats = 5;
    std::uint64_t seed = 12345;
    for (int i = 1; i + 1 < argc; i += 2) {
        const std::string a = argv[i];
        if (a == "--sizes") sizes = argv[i + 1];
        else if (a == "--steps") steps = std::atoi(argv[i + 1]);
        else if (a == "--repeats") repeats = std::atoi(argv[i + 1]);
        else if (a == "--seed") seed = std::strtoull(argv[i + 1], nullptr, 10);
        else { std::fprintf(stderr, "unknown option: %s\n", a.c_str()); return 2; }
    }
    if (steps < 1 || repeats < 1) { std::fprintf(stderr, "steps >= 1 and repeats >= 1 required\n"); return 2; }

    const nb::Params p;
    std::printf("Phase profile of the sequential step loop: %d steps, median of %d repeats, seed %llu\n", steps, repeats,
                static_cast<unsigned long long>(seed));
    std::printf("%-7s %10s %10s %10s %9s %9s %9s %9s\n", "N", "step_s", "force_s", "linear_s", "force_%", "linear_%",
                "sum/step", "spread_%");
    for (const std::size_t n : parse_sizes(sizes)) {
        if (n < 2) continue;
        nb::System init;
        nb::init_random(init, n, seed);
        nb::prepare(init, p);
        volatile double sink = 0.0;
        std::vector<double> t_step, t_force, t_linear;
        for (int r = 0; r < repeats; ++r) {
            nb::System s = init;
            auto t0 = Clock::now();
            for (int k = 0; k < steps; ++k) nb::step(s, p, nb::Variant::Seq, nb::Grain::Body);
            t_step.push_back(seconds_since(t0));

            s = init;
            t0 = Clock::now();
            for (int k = 0; k < steps; ++k) nb::compute_accel(s, p, nb::Variant::Seq, nb::Grain::Body);
            t_force.push_back(seconds_since(t0));

            s = init;
            t0 = Clock::now();
            for (int k = 0; k < steps; ++k) linear_loops(s, p);
            t_linear.push_back(seconds_since(t0));
            sink = sink + s.x[0] + s.vx[n - 1];  // keeps the compiler from dropping the timed work
        }
        const double ts = median(t_step), tf = median(t_force), tl = median(t_linear);
        const auto mm = std::minmax_element(t_step.begin(), t_step.end());
        const double parts = tf + tl;
        std::printf("%-7zu %10.4f %10.4f %10.6f %8.2f%% %8.3f%% %9.3f %8.2f%%\n", n, ts, tf, tl, 100.0 * tf / parts,
                    100.0 * tl / parts, parts / ts, 100.0 * (*mm.second - *mm.first) / ts);
    }
    std::puts("force = nb::compute_accel (O(N^2) pair loop); linear = kick, drift, kick (three O(N) loops).");
    std::puts("force% and linear% are shares of force + linear; sum/step should be 1.00 within the spread.");
    return 0;
}
