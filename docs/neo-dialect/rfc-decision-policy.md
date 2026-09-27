# neo-dialect RFC decision policy

Status: point 6 complete. **No RFC is currently classifiable.**

Reviewed: 2026-09-27.

## Current state

There are **0 admitted numbered RFCs**.

Therefore there is currently no valid subject to classify as:

- migliora
- neutra
- peggiora

Assigning one of those labels to a rejected candidate or to a non-existent 1.1 draft would manufacture evidence.

Current point-6 result: **N/A — no RFC admitted**.

## Future classification rule

Every future admitted RFC that reaches an A/B comparison must receive exactly one outcome.

### migliora

Use migliora only when:
- the RFC-defined semantic delta produces a reproducible improvement on its predeclared hypothesis;
- the improvement is attributable to the protocol change, not model/runtime noise;
- the result does not duplicate an A2A primitive;
- security, isolation and compatibility constraints remain satisfied;
- the Critic does not veto the RFC.

### neutra

Use neutra when:
- no material protocol-level improvement or degradation is demonstrated;
- differences fall within expected run/model variation;
- benefits are cosmetic, wording-only, or not attributable to the RFC;
- added complexity is not justified by a measurable gain.

A neutra RFC is **not eligible for promotion** merely because it did not cause regressions.

### peggiora

Use peggiora when the RFC causes any material regression, including:
- lower structured-message validity attributable to the change;
- more fallback usage;
- more negotiation loops;
- more turns without compensating benefit;
- lower RESULT/BYE completion;
- weaker injection resistance or broader attack surface;
- ambiguity or interoperability regressions;
- duplication/conflict with A2A.

## Critic veto

The Critic has an independent veto.

A veto is allowed even when headline metrics improve.

Mandatory veto conditions include:
- the RFC duplicates an A2A primitive or lifecycle function;
- the apparent improvement comes from changing the model, prompt, guard, scenario corpus or other non-RFC variable;
- security/isolation is weakened;
- the change creates hidden production influence or external contact;
- backward compatibility with 1.0 is broken without an explicitly approved migration design;
- the sample does not support attribution to the protocol delta;
- the RFC solves a MODEL problem rather than a DIALECT problem.

The Critic must record a concrete reason for every veto.

## Decision precedence

For an admitted RFC:

1. verify experiment integrity;
2. evaluate the predeclared A/B metrics;
3. assign provisional migliora, neutra or peggiora;
4. apply Critic review;
5. if Critic vetoes, final status is VETOED regardless of provisional metric outcome;
6. only a non-vetoed migliora result may be recommended to Andrea for approval.

No RFC is automatically promoted.

## Present candidate review

clarification_overloaded_into_counter is **not classified** under this policy because it never became an RFC.

Reason:
- the observation was real;
- A2A already covers the required clarification semantics;
- point 3 rejected creation of CLARIFY.

Its status remains **REJECTED_BEFORE_RFC**, not neutra or peggiora.

## Production boundary

This policy does not modify:
- docs/neo-dialect.md;
- schemas/neo-dialect/1.0/**;
- neo_dialect.py;
- the public /neo-dialect/1.0 contract.

No promotion can occur without Andrea's explicit approval.

## Point-6 conclusion

**0 RFC classified. 0 RFC recommended.**

The decision framework is now ready for future evidence, with Critic veto taking precedence over a favorable metric result.
