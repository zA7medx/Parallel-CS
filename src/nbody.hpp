// N-body simulation: direct summation, leapfrog (kick-drift-kick), softened gravity.
// One source tree, three builds: sequential (no OpenMP), OpenMP, debug. See ../README.md.
#pragma once
#include <cstddef>
#include <cstdint>
#include <vector>

namespace nb {

// How the shared potential-energy total is protected in the OpenMP versions.
enum class Variant {
    Seq,        // plain sequential loop (the baseline)
    Unsafe,     // shared total updated with no protection: a data race, for demonstration only
    Critical,   // updates inside an OpenMP critical section
    Atomic,     // updates with an OpenMP atomic operation
    Reduction   // private partial sums combined by an OpenMP reduction
};

// How often a thread touches the shared total.
enum class Grain {
    Body,  // once per body, after its inner loop (few updates)
    Pair   // once per pair of bodies (about N*N updates per step): makes the cost of protection visible
};

struct Params {
    double G = 1.0;     // gravitational constant (code units)
    double eps = 0.05;  // softening length: avoids huge forces in close encounters
    double dt = 0.001;  // time step
};

// Structure-of-arrays layout: one array per coordinate.
struct System {
    std::size_t n = 0;
    std::vector<double> x, y, z, vx, vy, vz, ax, ay, az, m;
    void resize(std::size_t count);
};

// Same seed, same n -> same initial state on every platform (own generator, no <random> distributions).
void init_random(System& s, std::size_t n, std::uint64_t seed);

// Fills ax, ay, az for every body. Returns the potential energy (each pair counted once).
double compute_accel(System& s, const Params& p, Variant v, Grain g);

// Kinetic energy (sequential, exact reference).
double kinetic_energy(const System& s);

// Potential energy by a plain sequential double loop (exact reference for checks).
double potential_energy_reference(const System& s, const Params& p);

// One leapfrog step. Accelerations must already be valid (call prepare once before the first step).
// Returns the potential energy accumulated by the chosen variant at the new positions.
double step(System& s, const Params& p, Variant v, Grain g);

// Computes the first accelerations with the sequential kernel.
void prepare(System& s, const Params& p);

bool openmp_enabled();

}  // namespace nb
