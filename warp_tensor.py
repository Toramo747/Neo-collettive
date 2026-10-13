# SPDX-License-Identifier: BUSL-1.1
"""Metric -> required stress tensor, in geometric units, Lambda=0.

This is inverse geometry evaluation, not a matter model or dynamical solver.
Equations: https://arxiv.org/abs/2404.03095, section 3.1.
Constant-speed comoving Alcubierre coordinates: x'=x-beta*t,
ds^2=-dt^2+(dx'+beta*(1-f)dt)^2+dy^2+dz^2.
"""
from __future__ import annotations

import itertools
import math
import numpy as np

from warp_physics import AlcubierreReference


def curvature(g, dg, ddg):
    """dg[k,i,j]=partial_k g_ij; ddg[k,l,i,j]=partial_k partial_l g_ij."""
    g, dg, ddg = (np.asarray(x, dtype=float) for x in (g, dg, ddg))
    if g.shape != (4, 4) or dg.shape != (4, 4, 4) or ddg.shape != (4, 4, 4, 4):
        raise ValueError("invalid metric derivative dimensions")
    if not all(np.isfinite(x).all() for x in (g, dg, ddg)):
        raise ValueError("non-finite metric derivatives")
    inverse = np.linalg.inv(g)
    dinverse = -np.einsum('ia,kab,bj->kij', inverse, dg, inverse)
    h = np.empty((4, 4, 4))
    dh = np.empty((4, 4, 4, 4))
    for s, b, c in itertools.product(range(4), repeat=3):
        h[s, b, c] = dg[b, s, c]+dg[c, s, b]-dg[s, b, c]
        for k in range(4):
            dh[k, s, b, c] = ddg[k, b, s, c]+ddg[k, c, s, b]-ddg[k, s, b, c]
    gamma = .5*np.einsum('as,sbc->abc', inverse, h)
    dgamma = .5*(np.einsum('kas,sbc->kabc', dinverse, h)
                 + np.einsum('as,ksbc->kabc', inverse, dh))
    riemann = np.empty((4, 4, 4, 4))
    for a, b, c, d in itertools.product(range(4), repeat=4):
        riemann[a, b, c, d] = (dgamma[c, a, d, b]-dgamma[d, a, c, b]
                               + np.dot(gamma[a, c], gamma[:, d, b])
                               - np.dot(gamma[a, d], gamma[:, c, b]))
    ricci = np.einsum('abad->bd', riemann)
    scalar = float(np.sum(inverse*ricci))
    lower = np.einsum('ae,ebcd->abcd', g, riemann)
    kretschmann = float(np.einsum('abcd,efgh,ae,bf,cg,dh', lower, lower,
                                  inverse, inverse, inverse, inverse, optimize=True))
    return {"ricci": ricci, "ricci_scalar": scalar,
            "christoffel": gamma,
            "stress_covariant": (ricci-.5*scalar*g)/(8*math.pi),
            "riemann_covariant": lower, "kretschmann": kretschmann}


def comoving_metric(metric: AlcubierreReference, point: tuple):
    x = np.asarray(point, dtype=float)
    if x.shape != (3,) or not np.isfinite(x).all():
        raise ValueError("invalid spatial point")
    r = float(np.linalg.norm(x))
    s = 1/metric.wall_scale
    def sech2(z):
        e = math.exp(-2*abs(z))
        return 4*e/(1+e)**2
    zp, zm = s*(r+metric.radius), s*(r-metric.radius)
    fsecond = s*s*(-sech2(zp)*math.tanh(zp)+sech2(zm)*math.tanh(zm))/math.tanh(s*metric.radius)
    b = metric.beta*(1-metric.shape(r))
    bfirst, bsecond = -metric.beta*metric.shape_derivative(r), -metric.beta*fsecond
    if r == 0:
        gradient = np.zeros(3)
        hessian = bsecond*np.eye(3)
    else:
        direction = x/r
        gradient = bfirst*direction
        hessian = (bsecond-bfirst/r)*np.outer(direction, direction)+bfirst/r*np.eye(3)
    g = np.eye(4)
    g[0, 0] = b*b-1
    g[0, 1] = g[1, 0] = b
    dg, ddg = np.zeros((4, 4, 4)), np.zeros((4, 4, 4, 4))
    for i in range(3):
        dg[i+1, 0, 0] = 2*b*gradient[i]
        dg[i+1, 0, 1] = dg[i+1, 1, 0] = gradient[i]
        for j in range(3):
            ddg[i+1, j+1, 0, 0] = 2*gradient[i]*gradient[j]+2*b*hessian[i, j]
            ddg[i+1, j+1, 0, 1] = ddg[i+1, j+1, 1, 0] = hessian[i, j]
    tetrad = np.eye(4)
    tetrad[1, 0] = -b
    return g, dg, ddg, tetrad


def point_tensor(metric: AlcubierreReference, point: tuple) -> dict:
    g, dg, ddg, tetrad = comoving_metric(metric, point)
    result = curvature(g, dg, ddg)
    stress = tetrad.T @ result["stress_covariant"] @ tetrad
    frame_riemann = np.einsum('ma,nb,pc,qd,mnpq->abcd', tetrad, tetrad,
                              tetrad, tetrad, result["riemann_covariant"], optimize=True)
    return {"point_over_L0": list(point),
            "stress_eulerian_times_L0_squared": stress.tolist(),
            "ricci_scalar_times_L0_squared": result["ricci_scalar"],
            "kretschmann_times_L0_fourth": result["kretschmann"],
            "tidal_eulerian_times_L0_squared": frame_riemann[0, 1:, 0, 1:].tolist()}


def observer_witnesses(stress: list) -> dict:
    """Finite sampling can find violations; cannot prove energy conditions."""
    t = np.asarray(stress)
    directions = [np.array(u, dtype=float)/np.linalg.norm(u)
                  for u in itertools.product((-1, 0, 1), repeat=3) if any(u)]
    null = [np.concatenate(([1.0], u)) for u in directions]
    timelike = [np.array([1., 0., 0., 0.])]
    timelike += [np.concatenate(([1.0], speed*u))/math.sqrt(1-speed*speed)
                 for speed in (.5, .9) for u in directions]
    def witness(vectors):
        values = [float(v @ t @ v) for v in vectors]
        i = int(np.argmin(values))
        tolerance = 1e-10*max(1., float(np.max(np.abs(t))))
        return {"minimum_sampled_contraction": values[i], "observer_in_eulerian_frame": vectors[i].tolist(),
                "status": "VIOLATION_FOUND" if values[i] < -tolerance else "NOT_ESTABLISHED",
                "observer_count": len(vectors), "numerical_tolerance": tolerance}
    return {"null_energy_condition": witness(null), "weak_energy_condition": witness(timelike),
            "all_observers_checked": False}


def schwarzschild_reference(mass=.1, radius=3., theta=1.1):
    """Analytic vacuum benchmark, coordinates (t,r,theta,phi), outside horizon."""
    a = 1-2*mass/radius
    ap, app = 2*mass/radius**2, -4*mass/radius**3
    sn, cs = math.sin(theta), math.cos(theta)
    g = np.diag([-a, 1/a, radius**2, radius**2*sn**2])
    dg, ddg = np.zeros((4, 4, 4)), np.zeros((4, 4, 4, 4))
    dg[1, 0, 0], ddg[1, 1, 0, 0] = -ap, -app
    dg[1, 1, 1], ddg[1, 1, 1, 1] = -ap/a**2, 2*ap**2/a**3-app/a**2
    dg[1, 2, 2], ddg[1, 1, 2, 2] = 2*radius, 2
    dg[1, 3, 3], ddg[1, 1, 3, 3] = 2*radius*sn**2, 2*sn**2
    dg[2, 3, 3], ddg[2, 2, 3, 3] = 2*radius**2*sn*cs, 2*radius**2*(cs**2-sn**2)
    ddg[1, 2, 3, 3] = ddg[2, 1, 3, 3] = 4*radius*sn*cs
    return g, dg, ddg


def de_sitter_reference(hubble=.2):
    """Flat-slicing de Sitter at t=0; Lambda=0 engine reports effective T."""
    g = np.diag([-1., 1., 1., 1.])
    dg, ddg = np.zeros((4, 4, 4)), np.zeros((4, 4, 4, 4))
    for i in range(1, 4):
        dg[0, i, i], ddg[0, 0, i, i] = 2*hubble, 4*hubble*hubble
    return g, dg, ddg


def tensor_benchmarks() -> dict:
    vacuum = curvature(*schwarzschild_reference())
    cosmological = curvature(*de_sitter_reference())
    metric = AlcubierreReference(1., .125, 1.)
    points = [(0., 1., 0.), (.6, .8, 0.), (0., 0., 0.)]
    density_error = max(abs(point_tensor(metric, p)["stress_eulerian_times_L0_squared"][0][0]
                            - metric.density(*p)) for p in points)
    g = de_sitter_reference()[0]
    checks = {
        "schwarzschild_vacuum": float(np.max(np.abs(vacuum["stress_covariant"]))) < 1e-12,
        "schwarzschild_kretschmann": abs(vacuum["kretschmann"]-48*.1**2/3**6) < 1e-12,
        "de_sitter_ricci_scalar": abs(cosmological["ricci_scalar"]-12*.2**2) < 1e-12,
        "de_sitter_full_tensor": float(np.max(np.abs(cosmological["stress_covariant"]+3*.2**2*g/(8*math.pi)))) < 1e-12,
        "alcubierre_published_density": density_error < 1e-10,
    }
    return {"passed": all(checks.values()), "checks": checks, "max_density_absolute_error": density_error}
