"""hackfront CLI: demo | sync | status | ask | serve."""

from __future__ import annotations

import argparse
import json
import sys

from . import config


def _print(obj) -> None:
    print(json.dumps(obj, indent=2))


def main(argv: list[str] | None = None) -> int:
    config.load_env()
    cli = argparse.ArgumentParser(prog="hackfront", description=__doc__)
    sub = cli.add_subparsers(dest="cmd", required=True)
    sub.add_parser("demo", help="load the synthetic demo workspace (no credentials needed besides Neo4j)")
    sub.add_parser("sync", help="ingest the sources named in workspace.json (needs tokens in env)")
    sub.add_parser("status", help="graph counts")
    ask = sub.add_parser("ask", help="ask the agent from the terminal")
    ask.add_argument("question")
    ask.add_argument("--mode", default="why", choices=["why", "debug", "change"])
    ask.add_argument("--provider", choices=["azure", "sarvam"])
    serve = sub.add_parser("serve", help="start the API and web UI")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    args = cli.parse_args(argv)

    if args.cmd in ("demo", "sync"):
        from .ingest.sync import graph_counts, sync_workspace

        if args.cmd == "demo":
            from .ingest.demo import DEMO_WORKSPACE

            summaries = sync_workspace(DEMO_WORKSPACE, demo=True)
        else:
            summaries = sync_workspace(config.load_workspace())
        _print(summaries)
        _print(graph_counts())
        return 0 if all(s["complete"] for s in summaries) else 1
    if args.cmd == "status":
        from .ingest.sync import graph_counts

        _print(graph_counts())
    elif args.cmd == "ask":
        from . import agent

        for event in agent.run(args.question, mode=args.mode, provider=args.provider):
            if event["event"] == "trace":
                print(f"[{event['node']}] {json.dumps(event['data'], default=str)[:300]}", file=sys.stderr)
            elif event["event"] == "answer":
                a = event["answer"]
                print(f"\n{a['answer']}\n\nconfidence: {a['confidence']}\nuncertainty: {a['uncertainty'] or '-'}")
                print("sources:\n" + "\n".join(f"  {c}" for c in a["citations"]))
                print(f"(attempts={a['attempts']}, {a['provider']}/{a['model']}, prompts={a['prompt_version']})")
            else:
                print(f"error: {event['message']}", file=sys.stderr)
                return 1
    elif args.cmd == "serve":
        import uvicorn

        uvicorn.run("hackfront.api:app", host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
