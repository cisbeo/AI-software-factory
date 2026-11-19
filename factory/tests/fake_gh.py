#!/usr/bin/env python3
"""A fake `gh` for the forge contract tests: a tiny in-memory GitHub.

It answers the REST calls the GitHub adapter makes (`gh api ...`) and
`gh pr ready`, from a JSON state file named by FAKE_GH_STATE, which it
rewrites after each call. Errors look like gh's: a JSON body on stdout,
`gh: <message> (HTTP <code>)` on stderr, exit status 1.

State keys: user, next, issues, comments, deps, deps_unavailable, pulls,
check_runs, statuses, reviews, protection, rules.
"""

import hashlib
import json
import os
import re
import sys
from urllib.parse import parse_qs, unquote, urlsplit


class HttpError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


def new_sha(state):
    state["next"] += 1
    return hashlib.sha1(str(state["next"]).encode()).hexdigest()


def next_number(state):
    state["next"] += 1
    return state["next"]


def issue_or_404(state, n):
    issue = state["issues"].get(str(n))
    if issue is None:
        raise HttpError(404, "Not Found")
    return issue


def pull_or_404(state, n):
    pull = state["pulls"].get(str(n))
    if pull is None:
        raise HttpError(404, "Not Found")
    return pull


def route(state, method, path, query, payload):
    user = state["user"]
    m = re.fullmatch(r"repos/[^/]+/[^/]+/(.*)", path)
    if path == "user" and method == "GET":
        return {"login": user}
    if not m:
        raise HttpError(404, "Not Found")
    rest = m.group(1)

    if rest == "issues" and method == "GET":
        want_state = query.get("state", "open")
        labels = [l for l in query.get("labels", "").split(",") if l]
        found = []
        for issue in state["issues"].values():
            names = {l["name"] for l in issue["labels"]}
            if want_state != "all" and issue["state"] != want_state:
                continue
            if all(l in names for l in labels):
                found.append(issue)
        return sorted(found, key=lambda i: -i["number"])
    if rest == "issues" and method == "POST":
        n = next_number(state)
        issue = {"number": n, "title": payload["title"], "body": payload.get("body", ""),
                 "user": {"login": user}, "state": "open",
                 "labels": [{"name": l} for l in payload.get("labels", [])],
                 "html_url": f"https://github.test/o/r/issues/{n}"}
        state["issues"][str(n)] = issue
        return issue

    if mm := re.fullmatch(r"issues/(\d+)", rest):
        issue = issue_or_404(state, mm.group(1))
        if method == "GET":
            return issue
        if method == "PATCH":
            issue.update({k: v for k, v in payload.items() if k in ("state", "title", "body")})
            return issue
    if mm := re.fullmatch(r"issues/(\d+)/comments", rest):
        issue_or_404(state, mm.group(1))
        comments = state["comments"].setdefault(mm.group(1), [])
        if method == "GET":
            return comments
        if method == "POST":
            c = {"user": {"login": user}, "body": payload["body"],
                 "created_at": f"2026-11-19T10:{len(comments):02d}:00Z"}
            comments.append(c)
            return c
    if mm := re.fullmatch(r"issues/(\d+)/labels", rest):
        issue = issue_or_404(state, mm.group(1))
        if method == "POST":
            for l in payload["labels"]:
                if l not in {x["name"] for x in issue["labels"]}:
                    issue["labels"].append({"name": l})
            return issue["labels"]
    if mm := re.fullmatch(r"issues/(\d+)/labels/(.+)", rest):
        issue = issue_or_404(state, mm.group(1))
        name = unquote(mm.group(2))
        if method == "DELETE":
            if name not in {x["name"] for x in issue["labels"]}:
                raise HttpError(404, "Label does not exist")
            issue["labels"] = [x for x in issue["labels"] if x["name"] != name]
            return issue["labels"]
    if mm := re.fullmatch(r"issues/(\d+)/dependencies/blocked_by", rest):
        issue_or_404(state, mm.group(1))
        if state.get("deps_unavailable"):
            raise HttpError(404, "Not Found")
        if method == "GET":
            return [state["issues"][str(b)] for b in state["deps"].get(mm.group(1), [])]

    if rest == "pulls" and method == "GET":
        head = query.get("head", "").split(":")[-1]
        want_state = query.get("state", "open")
        return [p for p in state["pulls"].values()
                if (not head or p["head"]["ref"] == head)
                and (want_state == "all" or p["state"] == want_state)]
    if rest == "pulls" and method == "POST":
        n = next_number(state)
        pull = {"number": n, "title": payload["title"], "body": payload.get("body", ""),
                "draft": bool(payload.get("draft")), "state": "open", "merged": False,
                "merged_at": None, "user": {"login": user},
                "head": {"ref": payload["head"], "sha": new_sha(state)},
                "base": {"ref": payload["base"]},
                "html_url": f"https://github.test/o/r/pull/{n}"}
        state["pulls"][str(n)] = pull
        state["issues"][str(n)] = {"number": n, "title": pull["title"], "body": pull["body"],
                                   "user": {"login": user}, "state": "open", "labels": [],
                                   "html_url": pull["html_url"], "pull_request": {"url": "x"}}
        return pull
    if mm := re.fullmatch(r"pulls/(\d+)", rest):
        pull = pull_or_404(state, mm.group(1))
        if method == "GET":
            return pull
        if method == "PATCH":
            pull.update({k: v for k, v in payload.items() if k in ("state", "title", "body")})
            return pull
    if mm := re.fullmatch(r"pulls/(\d+)/merge", rest):
        pull = pull_or_404(state, mm.group(1))
        if method == "PUT":
            if pull["merged"] or pull["state"] != "open":
                raise HttpError(405, "Pull Request is not mergeable")
            if pull["draft"]:
                raise HttpError(405, "Pull Request is still a draft")
            if payload.get("sha") and payload["sha"] != pull["head"]["sha"]:
                raise HttpError(409, "Head branch was modified. Review and try the merge again.")
            pull.update(merged=True, state="closed", merged_at="2026-11-19T11:00:00Z",
                        merge_method=payload.get("merge_method", "merge"))
            return {"sha": new_sha(state), "merged": True, "message": "Pull Request successfully merged"}
    if mm := re.fullmatch(r"pulls/(\d+)/reviews", rest):
        pull_or_404(state, mm.group(1))
        if method == "GET":
            return state["reviews"].get(mm.group(1), [])
    if mm := re.fullmatch(r"commits/([0-9a-f]+)/check-runs", rest):
        runs = state["check_runs"].get(mm.group(1), [])
        return {"total_count": len(runs), "check_runs": runs}
    if mm := re.fullmatch(r"commits/([0-9a-f]+)/status", rest):
        return {"statuses": state["statuses"].get(mm.group(1), [])}
    if mm := re.fullmatch(r"branches/([^/]+)/protection", rest):
        prot = state["protection"].get(unquote(mm.group(1)))
        if prot is None:
            raise HttpError(404, "Branch not protected")
        return prot
    if mm := re.fullmatch(r"rules/branches/([^/]+)", rest):
        return state["rules"].get(unquote(mm.group(1)), [])
    raise HttpError(404, "Not Found")


def parse_api(args):
    method, endpoint, payload, flags = "GET", None, None, set()
    it = iter(args)
    for a in it:
        if a in ("-X", "--method"):
            method = next(it)
        elif a == "--input":
            src = next(it)
            text = sys.stdin.read() if src == "-" else open(src).read()
            payload = json.loads(text) if text.strip() else {}
        elif a in ("-H", "--header", "--hostname"):
            next(it)
        elif a in ("--paginate", "--slurp"):
            flags.add(a)
        elif a.startswith("-"):
            raise SystemExit(f"fake gh: unsupported flag {a}")
        else:
            endpoint = a
    if payload is not None and method == "GET":
        method = "POST"
    return method, endpoint, payload or {}, flags


def main():
    path = os.environ["FAKE_GH_STATE"]
    with open(path) as f:
        state = json.load(f)
    args = sys.argv[1:]
    if os.environ.get("FAKE_GH_LOG"):
        with open(os.environ["FAKE_GH_LOG"], "a") as f:
            f.write(json.dumps(args) + "\n")
    if "-R" in args:
        i = args.index("-R")
        args = args[:i] + args[i + 2:]
    try:
        if args[:2] == ["pr", "ready"]:
            pull = pull_or_404(state, args[2])
            pull["draft"] = False
            out = None
        elif args[:1] == ["api"]:
            method, endpoint, payload, flags = parse_api(args[1:])
            parts = urlsplit(endpoint.lstrip("/"))
            query = {k: v[0] for k, v in parse_qs(parts.query).items()}
            out = route(state, method, parts.path, query, payload)
            if "--slurp" in flags:
                out = [out]
        else:
            raise SystemExit(f"fake gh: unsupported command {args}")
    except HttpError as e:
        print(json.dumps({"message": e.message}))
        print(f"gh: {e.message} (HTTP {e.code})", file=sys.stderr)
        sys.exit(1)
    with open(path, "w") as f:
        json.dump(state, f)
    if out is not None:
        print(json.dumps(out))


if __name__ == "__main__":
    main()
