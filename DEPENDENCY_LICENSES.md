# Dependency License Review

This review covers the direct runtime dependencies declared in `requirements.txt` and `jarvis_service/requirements.txt`.

| Dependency | Declared constraint | License | BUSL distribution review |
| --- | --- | --- | --- |
| mcp | ==2.2.0 | MIT | Permissive; no direct conflict identified |
| httpx | >=0.28,<1 | BSD-3-Clause | Permissive; no direct conflict identified |
| fastapi | >=0.115,<1 | MIT | Permissive; no direct conflict identified |
| uvicorn[standard] | >=0.30,<1 | BSD-3-Clause | Permissive; no direct conflict identified |
| pydantic | >=2.8,<3 | MIT | Permissive; no direct conflict identified |

No direct GPL or AGPL dependency is declared in the repository at this revision.

The repository does not currently contain a lockfile, and several requirements use version ranges or extras. The exact transitive dependency set can therefore change at install time. Before redistribution, generate a resolved dependency inventory and repeat the license scan.
