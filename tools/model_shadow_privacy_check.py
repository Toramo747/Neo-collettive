#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,re
from pathlib import Path
from typing import Any

FORBIDDEN_KEYS={"text","normalized_text","url","domain","title","body","snippet","source","canonical_problem","target_user","current_workaround"}
URL_RE=re.compile(r"https?://",re.I)
EMAIL_RE=re.compile(r"(?i)[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}")

def check_value(value: Any, path: str="$") -> None:
    if isinstance(value,dict):
        for key,item in value.items():
            if str(key) in FORBIDDEN_KEYS:
                raise ValueError("private_field:"+path+"."+str(key))
            check_value(item,path+"."+str(key))
    elif isinstance(value,list):
        for i,item in enumerate(value):
            check_value(item,f"{path}[{i}]")
    elif isinstance(value,str):
        if URL_RE.search(value):
            raise ValueError("url_value:"+path)
        if EMAIL_RE.search(value):
            raise ValueError("email_value:"+path)

def check_file(path: Path) -> None:
    data=json.loads(path.read_text(encoding="utf-8"))
    check_value(data)

def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument("paths",nargs="+")
    args=p.parse_args()
    for raw in args.paths:
        path=Path(raw)
        if path.is_file():
            check_file(path)
    print(json.dumps({"privacy_check":"ok","files":len(args.paths)},separators=(",",":")))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
