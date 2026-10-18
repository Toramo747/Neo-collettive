# Subluminal positive-energy shell — theory-only experiment

Reference: Bobrick & Martire, *Introducing Physical Warp Drives*,
Classical and Quantum Gravity **38** (2021) 105009,
https://doi.org/10.1088/1361-6382/abdf6e .
This notebook-style implementation is **our illustrative choice** within the
paper's static spherically symmetric class, not a reproduction of a specific
published shell profile and not a propulsion solution.

## Explicit geometry and stress-energy

Geometrized units G=c=1, signature (-+++). Comoving metric

`ds² = -A(r)dt² + dr²/(1-2m(r)/r) + r²dΩ²`.

With `a=0.7, b=1.3, M=0.014` (all lengths in an arbitrary common L0),
take `m(r)=0` inside a, `m(r)=M` outside b, and
`m(r)=M[10u³-15u⁴+6u⁵]`, `u=(r-a)/(b-a)`, in between.
Set radial pressure to zero (an explicit independent model assumption) and
`A'/A=2m/[r(r-2m)]`, matched to Schwarzschild at b.

Einstein's equations then demand
`rho=m'/(4*pi*r²)`, `p_r=0`,
`p_t=rho*m/[2(r-2m)]` (anisotropic TOV equilibrium).
As `m'>=0` and `2m/r < 0.1`, both NEC/WEC and DEC are
satisfied algebraically for the declared static profile.
These inequalities describe an *effective required stress tensor*; the
ability to manufacture such matter, dynamical stability and a practical engine
are not established. The outer vacuum is Schwarzschild, not a free
zero-gravity bubble transported through space.

`beta` is a label for a constant subluminal relative velocity: changing it
does not lower or produce the shell's energy. There is no acceleration,
braking, horizon analysis or mechanism for motion. No superluminal
transport is claimed.

## Checks / boundaries

`positive_energy_subluminal_assess(beta)` uses the same `curvature()`
Einstein-tensor implementation as the Alcubierre and wormhole work, with
two central-difference step sizes at five spatial radii, comparing all
four diagonal orthonormal stress entries to independent analytic formulas.
The numerical gate has an absolute error tolerance of 1e-6 L0^-2, requires
refinement improvement and checks sampled NEC, WEC and DEC. It also returns
the positive proper-volume Eulerian energy integral, distinct from ADM mass
and propulsion energy. Parameters outside the declared bounded domain
are rejected, especially beta >= 1.

This check is *isolated from* the arena champion selection and production;
it does not change the commercial gate, model ranking, state writes,
deployment filters, or public Common behavior. Claims of exact physical
feasibility are prohibited. Full regression suite and test output must be
reviewed before adoption; do not merge or deploy without Andrea's approval.
