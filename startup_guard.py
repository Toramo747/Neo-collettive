# SPDX-License-Identifier: BUSL-1.1
from __future__ import annotations
import os
import sys

from hidden_control_gate import enforce_hidden_control

def main() -> int:
    result=enforce_hidden_control()
    print(
        "hidden_control_gate="
        +("pass" if result.get("ok") else "fail")
        +" cases="+str(result.get("cases") or 0),
        flush=True,
    )
    os.execvp(sys.executable,[sys.executable,"cloud_mcp.py"])
    return 0

if __name__=="__main__":
    raise SystemExit(main())
