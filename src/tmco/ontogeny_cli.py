from __future__ import annotations
import argparse, json
from pathlib import Path
from .ontogeny import tournament

def _sha(ref: str) -> str:
    git=Path(".git")
    try:
        if ref=="HEAD":
            value=(git/"HEAD").read_text().strip()
            if not value.startswith("ref: "):return value
            ref=value[5:]
        loose=git/ref
        if loose.exists():return loose.read_text().strip()
        for line in (git/"packed-refs").read_text().splitlines():
            if line and not line.startswith(("#","^")) and line.split(" ",1)[1]==ref:return line.split(" ",1)[0]
    except (OSError,IndexError):pass
    return "UNKNOWN"

def main() -> None:
    parser=argparse.ArgumentParser(description="Reproducible Digital Ontogeny laboratory")
    parser.add_argument("--seed",type=int,default=42);parser.add_argument("--seeds",type=int,default=1)
    parser.add_argument("--episodes",type=int,default=8);parser.add_argument("--budget",type=int,default=100_000)
    parser.add_argument("--output")
    args=parser.parse_args(); seeds=[args.seed+i for i in range(args.seeds)]
    report=tournament(seeds,episodes=args.episodes,budget=args.budget,git_sha=_sha("HEAD"),main_sha=_sha("main"))
    content=json.dumps(report,sort_keys=True,indent=2)
    if args.output:open(args.output,"w",encoding="utf-8").write(content+"\n")
    print(content)

if __name__=="__main__":main()
