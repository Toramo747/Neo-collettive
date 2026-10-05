# Warp arena: minimum physical reference

The evolutionary arena retains its original heuristic fitness and selection.
`physical_evaluation` is an observational report computed each generation, not
a physical promotion gate or a claim that the candidates are feasible.
No new families or evolutionary genes are introduced by this change.

## Geometry and source

Original implementation of formulas from Miguel Alcubierre, *The warp drive:
hyper-fast travel within general relativity*, Class. Quantum Grav. 11 (1994),
L73–L77; https://arxiv.org/abs/gr-qc/0009013, equations 6, 8, 10 and 19.

Signature -+++, G=c=1, lapse alpha=1, spatial metric delta_ij, shift
(-beta f(r),0,0), evaluated on a slice centered at the bubble:

    ds² = -dt² + (dx-beta f(r) dt)² + dy² + dz²
    f(r) = [tanh(sigma(r+R))-tanh(sigma(r-R))]/[2 tanh(sigma R)]
    rho_E = -beta² (y²+z²)/r² [f'(r)]²/(32 pi)

The Eulerian observer is normal to the constant-time spatial slices. The
independent numerical route differentiates the shift, constructs K_ij, then
uses the Hamiltonian constraint rho_E=(K²-K_ij K^ij)/(16 pi), since the
intrinsic spatial curvature is zero. This first report evaluates only this
projection of the Einstein equations. The separate `fixed_target_research`
track below computes the complete required stress tensor at sampled points.

Angular integration gives the Eulerian energy volume integral:

    E_E = -beta²/12 integral_0^infinity r² [f'(r)]² dr

This is not ADM mass, a conserved total energy, or a propulsion energy budget.
Radius and wall scale share an unspecified length unit L0. Reported quantities
are E_E/L0 and rho_E L0² in geometric units; no meters or joules are inferred.

## Mapping and coverage

For `alcubierre_like` only: R=bubble_radius, beta=effective_beta,
sigma=1/wall_thickness. This last mapping is a modeling convention; the wall
parameter is not a measured physical wall width. `shear_control` and
`lapse_modulation` have no geometry here and are explicitly reported as
unmodeled. The result is therefore `REFERENCE_METRIC_ONLY`, not a full
physical evaluation of the candidate. Other family names return
`UNSUPPORTED_GEOMETRY`, with no energy value or positive-energy claim.

Validated bounded parameter domain: R in [0.5,3], wall scale in [0.08,1.25],
|beta| <= 1.5, all finite. Invalid values fail closed.

## Reproducible controls

- Zero velocity: Minkowski limit and zero Eulerian energy density/integral.
- Normalized profile center and negative equatorial density for nonzero beta.
- Published density versus independent finite-difference Hamiltonian route,
  with halved derivative spacing improving the error.
- An independent Gaussian profile f=exp(-r²): its analytically derived
  integral is E_E=-sqrt(pi)/(32 sqrt(2)) for beta=R=1.
- Quadratic velocity scaling and linear common-length scaling of E_E.
- Composite Simpson integration with 512 versus 1024 intervals, and domain
  extension from R+12 wall scales to R+16 wall scales. Relative differences
  must be below 1e-5; domain corners are tested. These differences are
  convergence diagnostics, not rigorous error bounds.

Failed reference benchmarks abort a generation before its state is written.
Candidate convergence failures are reported and counted, never hidden or
converted to feasibility. Negative Eulerian density is a witness of weak
energy-condition violation; a zero sample is not proof of any energy condition.
No stability, horizons, causal structure, material realizability or full
Einstein-system validation is inferred. The schedule remains every six hours.

## Full tensor and fixed-target reference research

`warp_tensor.py` uses analytic first and second derivatives of the metric,
Christoffel symbols and their derivatives to construct Riemann, Ricci and
Einstein tensors. It computes the required source T_mu_nu=G_mu_nu/(8 pi),
with Lambda=0. These formulas are standard GR; methodological reference:
Helmerich et al., *Analyzing Warp Drive Spacetimes with Warp Factory* (2024),
https://arxiv.org/abs/2404.03095, sections 3.1 and 3.2. This is an original
Python implementation; no Warp Factory software is imported or copied.

For constant beta, comoving coordinates x'=x-beta*t give the stationary,
equivalent metric:

    ds² = -dt² + (dx'+beta(1-f(r))dt)² + dy² + dz²

Setting time derivatives to zero in this coordinate system is justified;
doing so for the original moving bubble would be incorrect. See also
Barzegar, Buchert and Vigneron (2026), preprint,
https://arxiv.org/abs/2602.16495, section III.8, for this representation.

The orthonormal Eulerian tetrad has e_0=(1,-beta(1-f),0,0), and spatial
coordinate unit vectors. The report retains the full symmetric stress tensor
at the center and three wall directions, and summarizes all 16 spatial
samples. It includes Ricci scalar, Kretschmann invariant and tidal matrix
R_hat(0,i,0,j). Tidal quantities are geometric curvature components, without
a physical length or acceleration conversion, not a passenger safety verdict.

At each point, 26 normalized null directions and 53 unit timelike observers
(rest plus speeds 0.5 and 0.9 in the Eulerian frame) sample NEC and WEC. A
negative contraction beyond the declared numerical tolerance is a violation
witness. No finite sample can certify the conditions for all observers and
spacetime points. SEC and DEC are not assessed by this track.

The evolving reference-profile comparison fixes R=1 L0 and runs separate
beta=0.8 and beta=1.1 targets. These are metric parameters, not achieved
spacecraft speeds. Only wall scale varies; this cannot improve the result by
slowing the target or shrinking the radius. Declared research constraints
require f(0.5 L0)>=0.99 and f(2 L0)<=0.01. These are profile constraints,
not a proof of an exactly flat, safe passenger region or actual transport.

Each target compares 12 wall profiles, with an always-present published
R=1, sigma=8 reference. Baseline walls are 0.08, 0.10, 0.125, 0.15, 0.18,
0.20, 0.22 and 0.25. Up to four prior champion scales seed bounded mutations
(0.85..1.15 multipliers within the validated domain). Numerical mismatches,
unconverged energy quadrature and failed profile constraints exclude a
profile from reference selection. Benchmarks must pass before any state write.

Selection uses a Pareto comparison minimizing absolute Eulerian volume energy
integral, maximum sampled tidal component, and maximum sampled interior tidal
component. A profile dominates another only if none of these gets worse and
at least one improves. Energy and interior-tide extremes from the front seed
the next generation, stored in `state.reference_search`. The original
heuristic champions and selection are untouched. Selection eligibility here
means a comparable reference profile, never physical viability: NEC/WEC
violations remain explicitly reported, including for selected profiles.

The tide samples use center, radial distances 0.5, R-wall_scale, R,
R+wall_scale and 2, and axial/equatorial/45-degree directions. Reported
maxima are sampled maxima, not bounds over all space. Consequently the
Pareto result is approximate and needs denser independent verification before
any scientific claim. No stability, global causality, creation/acceleration/
braking, realizable matter source, or laboratory experiment is supplied.
Inverse T=G/(8 pi) alone does not establish a physically realizable solution.

Independent tests include Schwarzschild vacuum and its curvature invariant,
de Sitter full effective stress tensor, Minkowski limit, published Alcubierre
density, all stress components versus independently differenced metrics with
grid refinement, Riemann identities, tetrad normalization, dimensional
scaling and finite-difference covariant conservation of stress energy.

NumPy 2.3.3 is already pinned in the project runtime requirements and is
installed explicitly by the isolated arena workflow. CPU only; no paid API.

Run: `python -m unittest -v test_arena_warp_propulsion test_warp_physics test_warp_tensor`.
