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
intrinsic spatial curvature is zero. Only this projection of the Einstein
equations is evaluated; the full stress-energy tensor is not computed.

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

Run: `python -m unittest -v test_arena_warp_propulsion test_warp_physics`.
