#include "nbody.hpp"

#include <cmath>

namespace nb {

bool openmp_enabled() {
#ifdef _OPENMP
    return true;
#else
    return false;
#endif
}

void System::resize(std::size_t count) {
    n = count;
    for (auto* v : {&x, &y, &z, &vx, &vy, &vz, &ax, &ay, &az, &m}) v->assign(count, 0.0);
}

// ---------- seeded input (splitmix64) ----------
static inline std::uint64_t splitmix64(std::uint64_t& state) {
    std::uint64_t z = (state += 0x9E3779B97F4A7C15ULL);
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    return z ^ (z >> 31);
}
static inline double uniform01(std::uint64_t& state) {
    return static_cast<double>(splitmix64(state) >> 11) * (1.0 / 9007199254740992.0);  // 2^-53
}

void init_random(System& s, std::size_t n, std::uint64_t seed) {
    s.resize(n);
    std::uint64_t st = seed;
    const double mass = 1.0 / static_cast<double>(n);  // total mass 1
    for (std::size_t i = 0; i < n; ++i) {
        s.x[i] = 2.0 * uniform01(st) - 1.0;
        s.y[i] = 2.0 * uniform01(st) - 1.0;
        s.z[i] = 2.0 * uniform01(st) - 1.0;
        s.vx[i] = 0.2 * (uniform01(st) - 0.5);
        s.vy[i] = 0.2 * (uniform01(st) - 0.5);
        s.vz[i] = 0.2 * (uniform01(st) - 0.5);
        s.m[i] = mass;
    }
}

// ---------- kernels ----------
// The self term (j == i) gives zero force because dx = dy = dz = 0, and a potential of -G m_i^2 / eps.
// We keep it in the inner loop (no branch) and add it back once per body.

static double accel_seq(System& s, const Params& p) {
    const std::size_t n = s.n;
    const double eps2 = p.eps * p.eps;
    double pot = 0.0;
    for (std::size_t i = 0; i < n; ++i) {
        double axi = 0, ayi = 0, azi = 0, pei = 0;
        const double xi = s.x[i], yi = s.y[i], zi = s.z[i], mi = s.m[i];
        for (std::size_t j = 0; j < n; ++j) {
            const double dx = s.x[j] - xi, dy = s.y[j] - yi, dz = s.z[j] - zi;
            const double inv = 1.0 / std::sqrt(dx * dx + dy * dy + dz * dz + eps2);
            const double f = p.G * s.m[j] * inv * inv * inv;
            axi += f * dx; ayi += f * dy; azi += f * dz;
            pei -= p.G * mi * s.m[j] * inv;
        }
        pei += p.G * mi * mi / p.eps;  // remove the self term
        s.ax[i] = axi; s.ay[i] = ayi; s.az[i] = azi;
        pot += pei;
    }
    return 0.5 * pot;  // every pair was counted twice
}

// DEMONSTRATION ONLY. 'pot' is shared and updated without protection: this is a data race
// (undefined behaviour in C++). Expect wrong totals when more than one thread runs.
template <Grain G>
static double accel_unsafe(System& s, const Params& p) {
    const long n = static_cast<long>(s.n);
    const double eps2 = p.eps * p.eps;
    double pot = 0.0;
#pragma omp parallel for schedule(runtime)
    for (long i = 0; i < n; ++i) {
        double axi = 0, ayi = 0, azi = 0, pei = 0;
        const double xi = s.x[i], yi = s.y[i], zi = s.z[i], mi = s.m[i];
        for (long j = 0; j < n; ++j) {
            const double dx = s.x[j] - xi, dy = s.y[j] - yi, dz = s.z[j] - zi;
            const double inv = 1.0 / std::sqrt(dx * dx + dy * dy + dz * dz + eps2);
            const double f = p.G * s.m[j] * inv * inv * inv;
            axi += f * dx; ayi += f * dy; azi += f * dz;
            const double pair = -p.G * mi * s.m[j] * inv;
            if constexpr (G == Grain::Pair) pot += pair; else pei += pair;
        }
        const double self = p.G * mi * mi / p.eps;
        s.ax[i] = axi; s.ay[i] = ayi; s.az[i] = azi;
        if constexpr (G == Grain::Pair) pot += self; else pot += pei + self;
    }
    return 0.5 * pot;
}

template <Grain G>
static double accel_critical(System& s, const Params& p) {
    const long n = static_cast<long>(s.n);
    const double eps2 = p.eps * p.eps;
    double pot = 0.0;
#pragma omp parallel for schedule(runtime)
    for (long i = 0; i < n; ++i) {
        double axi = 0, ayi = 0, azi = 0, pei = 0;
        const double xi = s.x[i], yi = s.y[i], zi = s.z[i], mi = s.m[i];
        for (long j = 0; j < n; ++j) {
            const double dx = s.x[j] - xi, dy = s.y[j] - yi, dz = s.z[j] - zi;
            const double inv = 1.0 / std::sqrt(dx * dx + dy * dy + dz * dz + eps2);
            const double f = p.G * s.m[j] * inv * inv * inv;
            axi += f * dx; ayi += f * dy; azi += f * dz;
            const double pair = -p.G * mi * s.m[j] * inv;
            if constexpr (G == Grain::Pair) {
#pragma omp critical(nbody_pot)
                pot += pair;
            } else {
                pei += pair;
            }
        }
        const double self = p.G * mi * mi / p.eps;
        s.ax[i] = axi; s.ay[i] = ayi; s.az[i] = azi;
        if constexpr (G == Grain::Pair) {
#pragma omp critical(nbody_pot)
            pot += self;
        } else {
            const double total = pei + self;
#pragma omp critical(nbody_pot)
            pot += total;
        }
    }
    return 0.5 * pot;
}

template <Grain G>
static double accel_atomic(System& s, const Params& p) {
    const long n = static_cast<long>(s.n);
    const double eps2 = p.eps * p.eps;
    double pot = 0.0;
#pragma omp parallel for schedule(runtime)
    for (long i = 0; i < n; ++i) {
        double axi = 0, ayi = 0, azi = 0, pei = 0;
        const double xi = s.x[i], yi = s.y[i], zi = s.z[i], mi = s.m[i];
        for (long j = 0; j < n; ++j) {
            const double dx = s.x[j] - xi, dy = s.y[j] - yi, dz = s.z[j] - zi;
            const double inv = 1.0 / std::sqrt(dx * dx + dy * dy + dz * dz + eps2);
            const double f = p.G * s.m[j] * inv * inv * inv;
            axi += f * dx; ayi += f * dy; azi += f * dz;
            const double pair = -p.G * mi * s.m[j] * inv;
            if constexpr (G == Grain::Pair) {
#pragma omp atomic
                pot += pair;
            } else {
                pei += pair;
            }
        }
        const double self = p.G * mi * mi / p.eps;
        s.ax[i] = axi; s.ay[i] = ayi; s.az[i] = azi;
        if constexpr (G == Grain::Pair) {
#pragma omp atomic
            pot += self;
        } else {
            const double total = pei + self;
#pragma omp atomic
            pot += total;
        }
    }
    return 0.5 * pot;
}

// Each thread keeps a private partial sum; OpenMP combines them once at the end.
// The grain setting does not matter here (no shared update inside the loop).
static double accel_reduction(System& s, const Params& p) {
    const long n = static_cast<long>(s.n);
    const double eps2 = p.eps * p.eps;
    double pot = 0.0;
#pragma omp parallel for schedule(runtime) reduction(+ : pot)
    for (long i = 0; i < n; ++i) {
        double axi = 0, ayi = 0, azi = 0, pei = 0;
        const double xi = s.x[i], yi = s.y[i], zi = s.z[i], mi = s.m[i];
        for (long j = 0; j < n; ++j) {
            const double dx = s.x[j] - xi, dy = s.y[j] - yi, dz = s.z[j] - zi;
            const double inv = 1.0 / std::sqrt(dx * dx + dy * dy + dz * dz + eps2);
            const double f = p.G * s.m[j] * inv * inv * inv;
            axi += f * dx; ayi += f * dy; azi += f * dz;
            pei -= p.G * mi * s.m[j] * inv;
        }
        pei += p.G * mi * mi / p.eps;
        s.ax[i] = axi; s.ay[i] = ayi; s.az[i] = azi;
        pot += pei;
    }
    return 0.5 * pot;
}

double compute_accel(System& s, const Params& p, Variant v, Grain g) {
    switch (v) {
        case Variant::Seq: return accel_seq(s, p);
        case Variant::Unsafe:
            return g == Grain::Pair ? accel_unsafe<Grain::Pair>(s, p) : accel_unsafe<Grain::Body>(s, p);
        case Variant::Critical:
            return g == Grain::Pair ? accel_critical<Grain::Pair>(s, p) : accel_critical<Grain::Body>(s, p);
        case Variant::Atomic:
            return g == Grain::Pair ? accel_atomic<Grain::Pair>(s, p) : accel_atomic<Grain::Body>(s, p);
        case Variant::Reduction: return accel_reduction(s, p);
    }
    return 0.0;
}

double kinetic_energy(const System& s) {
    double k = 0.0;
    for (std::size_t i = 0; i < s.n; ++i)
        k += 0.5 * s.m[i] * (s.vx[i] * s.vx[i] + s.vy[i] * s.vy[i] + s.vz[i] * s.vz[i]);
    return k;
}

double potential_energy_reference(const System& s, const Params& p) {
    const double eps2 = p.eps * p.eps;
    double pot = 0.0;
    for (std::size_t i = 0; i < s.n; ++i)
        for (std::size_t j = i + 1; j < s.n; ++j) {
            const double dx = s.x[j] - s.x[i], dy = s.y[j] - s.y[i], dz = s.z[j] - s.z[i];
            pot -= p.G * s.m[i] * s.m[j] / std::sqrt(dx * dx + dy * dy + dz * dz + eps2);
        }
    return pot;
}

void prepare(System& s, const Params& p) { accel_seq(s, p); }

double step(System& s, const Params& p, Variant v, Grain g) {
    const std::size_t n = s.n;
    // The three O(N) loops below stay sequential: their cost is tiny next to the O(N^2) force loop.
    for (std::size_t i = 0; i < n; ++i) {  // kick (half step)
        s.vx[i] += 0.5 * p.dt * s.ax[i]; s.vy[i] += 0.5 * p.dt * s.ay[i]; s.vz[i] += 0.5 * p.dt * s.az[i];
    }
    for (std::size_t i = 0; i < n; ++i) {  // drift
        s.x[i] += p.dt * s.vx[i]; s.y[i] += p.dt * s.vy[i]; s.z[i] += p.dt * s.vz[i];
    }
    const double pot = compute_accel(s, p, v, g);  // forces at the new positions
    for (std::size_t i = 0; i < n; ++i) {  // kick (second half step)
        s.vx[i] += 0.5 * p.dt * s.ax[i]; s.vy[i] += 0.5 * p.dt * s.ay[i]; s.vz[i] += 0.5 * p.dt * s.az[i];
    }
    return pot;
}

}  // namespace nb
