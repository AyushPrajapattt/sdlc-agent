"""hackfront CLI: demo | sync | workspaces | status | ask | serve."""

from __future__ import annotations

import argparse
import json
import sys
import time

from . import config


def _print(obj) -> None:
    print(json.dumps(obj, indent=2))


def _sync(slug: str, mode: str) -> int:
    """Run a sync job to completion, printing a line whenever a stream changes."""
    from .ingest import sync

    status, seen = sync.start_sync(slug, mode), {}
    while True:
        status = sync.sync_status(slug)
        for s in status["streams"]:
            line = f"{s['stream']}: {s['status']} pages={s['pages']} fetched={s['fetched']} persisted={s['persisted']}"
            if seen.get(s["stream"]) != line:
                seen[s["stream"]] = line
                print(line + "".join(f"  ! {e['message']}" for e in s["errors"][:1]))
        if status["state"] != "running":
            break
        time.sleep(0.2)
    if status.get("error"):
        print(f"error: {status['error']}", file=sys.stderr)
    _print({"totals": status["totals"], "graph": status.get("graph"), "complete": status["complete"]})
    return 0 if status["complete"] else 1


def main(argv: list[str] | None = None) -> int:
    config.load_env()
    cli = argparse.ArgumentParser(prog="hackfront", description=__doc__)
    sub = cli.add_subparsers(dest="cmd", required=True)
    sub.add_parser("demo", help="create the 'demo' workspace if missing and sync it (needs only Neo4j)")
    sync = sub.add_parser("sync", help="ingest a workspace's sources (credentials from the workspace store or env)")
    sync.add_argument("--workspace", required=True)
    sync.add_argument("--deep", action="store_true", help="100 pages per stream instead of 20")
    sub.add_parser("workspaces", help="list workspaces")
    sub.add_parser("status", help="workspaces and global graph counts")
    ask = sub.add_parser("ask", help="ask the agent from the terminal")
    ask.add_argument("question")
    ask.add_argument("--workspace", required=True)
    ask.add_argument("--mode", default="why", choices=["why", "debug", "change"])
    ask.add_argument("--provider", choices=["azure", "sarvam"])
    migrate = sub.add_parser("migrate-state", help="copy local workspaces, saved keys and investigations into Neo4j")
    migrate.add_argument("--overwrite", action="store_true", help="replace workspaces that already exist in Neo4j")
    serve = sub.add_parser("serve", help="start the API and web UI")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    args = cli.parse_args(argv)

    try:
        if args.cmd == "demo":
            from .ingest.demo import DEMO_WORKSPACE

            if not any(w["slug"] == "demo" for w in config.list_workspaces()):
                config.create_workspace("Acme Demo", demo=True, slug="demo")
            config.save_workspace("demo", DEMO_WORKSPACE)
            return _sync("demo", "standard")
        if args.cmd == "sync":
            return _sync(args.workspace, "deep" if args.deep else "standard")
        if args.cmd == "migrate-state":
            from . import state

            result = state.migrate(state.FileState(), state.Neo4jState(), overwrite=args.overwrite)
            _print(result)
            if result["secrets_skipped"]:
                print("note: saved keys were NOT copied; set HACKFRONT_SECRET_KEY and run again with --overwrite", file=sys.stderr)
            return 0
        if args.cmd == "workspaces":
            for w in config.list_workspaces():
                print(f"{w['slug']}\t{w['name']}{'\t(demo)' if w['demo'] else ''}")
        elif args.cmd == "status":
            from .ingest.sync import graph_counts

            _print({"workspaces": config.list_workspaces(), "graph": graph_counts()})
        elif args.cmd == "ask":
            from . import agent
            from .api.mapping import flat_scopes

            events = agent.run(args.question, mode=args.mode, provider=args.provider,
                               scopes=flat_scopes(config.scopes(args.workspace)), workspace=args.workspace)
            for event in events:
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
    except (LookupError, ValueError, RuntimeError) as error:  # unknown workspace, no sources, already running, Neo4j env
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
