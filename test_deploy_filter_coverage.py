# SPDX-License-Identifier: BUSL-1.1
"""Every module the production server imports must trigger a deploy when it changes.

Found 2026-10-11: price_validation.py (and 32 other runtime modules) were missing
from the NEO Render Deploy path filter, so merged fixes reached production only
with an unrelated later deploy.
"""
import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def runtime_modules(entry: str = "cloud_mcp") -> set[str]:
    local = {p.stem for p in ROOT.glob("*.py")}
    seen, todo = set(), [entry]
    while todo:
        mod = todo.pop()
        if mod in seen:
            continue
        seen.add(mod)
        try:
            tree = ast.parse((ROOT / f"{mod}.py").read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                todo += [a.name.split(".")[0] for a in node.names if a.name.split(".")[0] in local]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                name = node.module.split(".")[0]
                if name in local:
                    todo.append(name)
    return {f"{m}.py" for m in seen}


class DeployFilterCoverageTests(unittest.TestCase):
    def test_every_runtime_module_triggers_a_deploy(self):
        wf = (ROOT / ".github/workflows/neo-render-deploy.yml").read_text(encoding="utf-8")
        block = wf[wf.index("paths:"):wf.index("jobs:")]
        listed = set(re.findall(r'"([^"]+)"', block))
        missing = sorted(runtime_modules() - listed)
        self.assertEqual(missing, [], f"add to the NEO Render Deploy path filter: {missing}")


if __name__ == "__main__":
    unittest.main()
