"""Minimal read-only GitHub REST client (GET only) with optional record/replay.

The token is read from the environment (GITHUB_TOKEN / GH_TOKEN) or, as a
fallback, from `gh auth token` at runtime. It is never written anywhere.
Recorded fixtures store only response status + JSON body, never headers.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.github.com"


def _token() -> str | None:
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        return tok
    try:
        r = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=10)
        return r.stdout.strip() or None
    except Exception:
        return None


def fixture_name(path: str) -> str:
    return hashlib.sha1(path.encode()).hexdigest()[:16] + ".json"


class GitHub:
    """GET-only client. `record_dir` saves responses; `replay_dir` serves them offline."""

    def __init__(self, token: str | None = None, record_dir: str | None = None,
                 replay_dir: str | None = None, max_calls: int = 2000):
        self.replay_dir = replay_dir
        self.record_dir = record_dir
        self.token = None if replay_dir else (token or _token())
        self.calls = 0
        self.max_calls = max_calls

    def get(self, path: str) -> tuple[int, object]:
        path = path.lstrip("/")
        if self.replay_dir:
            p = os.path.join(self.replay_dir, fixture_name(path))
            if not os.path.exists(p):
                return 404, {"message": "Not Found (no fixture)"}
            d = json.load(open(p))
            return d["status"], d["data"]
        if self.calls >= self.max_calls:
            raise RuntimeError("API call budget exhausted")
        req = urllib.request.Request(f"{API}/{path}", method="GET")
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        req.add_header("User-Agent", "bounty-ghostbuster/0.1")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        status, data = 0, None
        for attempt in range(4):
            self.calls += 1
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    status, body = r.status, r.read()
            except urllib.error.HTTPError as e:
                status, body = e.code, e.read()
                if status in (403, 429) and e.headers.get("x-ratelimit-remaining") == "0":
                    reset = int(e.headers.get("x-ratelimit-reset", "0") or 0)
                    time.sleep(min(max(reset - time.time() + 1, 5), 120))
                    continue
            except urllib.error.URLError:
                time.sleep(2 * (attempt + 1))
                continue
            if status >= 500:
                time.sleep(2 * (attempt + 1))
                continue
            try:
                data = json.loads(body) if body else None
            except ValueError:
                data = None
            break
        if self.record_dir:
            os.makedirs(self.record_dir, exist_ok=True)
            with open(os.path.join(self.record_dir, fixture_name(path)), "w") as f:
                json.dump({"path": path, "status": status, "data": data}, f)
        return status, data

    def pages(self, path: str, maxpages: int = 3) -> list:
        out: list = []
        sep = "&" if "?" in path else "?"
        for p in range(1, maxpages + 1):
            st, d = self.get(f"{path}{sep}per_page=100&page={p}")
            if st != 200 or not isinstance(d, list):
                break
            out += d
            if len(d) < 100:
                break
        return out

    def search_issues(self, q: str, limit: int = 50) -> tuple[int, list]:
        """REST issue search; falls back to GraphQL search (separate budget) on rate limits.
        Raises RuntimeError instead of silently returning zero results."""
        items: list = []
        total = None
        for p in range(1, 11):
            st, d = self.get("search/issues?q=" + urllib.parse.quote(q) + f"&sort=updated&order=desc&per_page=100&page={p}")
            if st != 200 or not isinstance(d, dict):
                if p == 1:
                    return self.search_issues_gql(q, limit)
                break
            total = d.get("total_count", 0)
            items += d.get("items", [])
            if not d.get("items") or len(items) >= min(limit, total):
                break
        return total or 0, items[:limit]

    GQL = ("query($q:String!,$after:String){search(query:$q,type:ISSUE,first:50,after:$after){issueCount "
           "pageInfo{hasNextPage endCursor} nodes{... on Issue{number title url createdAt updatedAt state locked "
           "repository{nameWithOwner} labels(first:20){nodes{name}} comments{totalCount}}}}}")

    def graphql(self, query: str, variables: dict) -> tuple[int, object]:
        """GraphQL is POST-only on GitHub; used here strictly for read-only search queries."""
        if self.replay_dir:
            return self.get("graphql?" + urllib.parse.urlencode({"v": json.dumps(variables, sort_keys=True)}))
        body = json.dumps({"query": query, "variables": variables}).encode()
        req = urllib.request.Request(f"{API}/graphql", data=body, method="POST")
        req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("User-Agent", "bounty-ghostbuster/0.1")
        self.calls += 1
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, None

    def search_issues_gql(self, q: str, limit: int) -> tuple[int, list]:
        items, after, total = [], None, None
        for _ in range(20):
            d = None
            for attempt in range(4):
                st, r = self.graphql(self.GQL, {"q": q, "after": after})
                d = ((r or {}).get("data") or {}).get("search") if isinstance(r, dict) else None
                if d:
                    break
                time.sleep(15 * (attempt + 1))
            if not d:
                raise RuntimeError(f"GitHub search unavailable (rate limited) for query: {q}")
            total = d["issueCount"]
            for n in d["nodes"]:
                if not n:
                    continue
                rp = n["repository"]["nameWithOwner"]
                items.append({"html_url": n["url"], "number": n["number"], "title": n["title"],
                              "created_at": n["createdAt"], "updated_at": n["updatedAt"], "state": n["state"].lower(),
                              "locked": n["locked"], "repository_url": f"{API}/repos/{rp}",
                              "comments": n["comments"]["totalCount"],
                              "labels": [{"name": l["name"]} for l in n["labels"]["nodes"]]})
            if len(items) >= limit or not d["pageInfo"]["hasNextPage"]:
                break
            after = d["pageInfo"]["endCursor"]
        return total or 0, items[:limit]
