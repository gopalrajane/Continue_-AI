"""Repository analysis: commits -> contribution map, dependency graph, decisions, open work."""
import collections, hashlib, itertools, json, os, re, shutil, subprocess, tempfile
import networkx as nx

# ---------------------------------------------------------------- ingestion
def _git(args):
    r = subprocess.run(["git"] + args, capture_output=True, text=True, timeout=180)
    if r.returncode:
        raise ValueError(r.stderr.strip()[-300:] or "git command failed")
    return r.stdout


def load_commits(source):
    """Return (commits, base_url). Source: 'demo', GitHub URL, owner/repo, or a local path."""
    src = source.strip()
    if src.lower() == "demo":
        return demo_commits(), ""
    if not os.path.isdir(src) and re.match(r"^[\w.-]+/[\w.-]+$", src):
        src = "https://github.com/" + src
    tmp = None
    try:
        if re.match(r"^(https?://|git@)", src):
            tmp = tempfile.mkdtemp()
            _git(["clone", "--bare", "--filter=blob:none", "--depth", "300", src, tmp])
            path = tmp
        elif os.path.isdir(src):
            path = src
        else:
            raise ValueError("Enter a GitHub URL, owner/repo, a local repository path, or 'demo'.")
        out = _git(["-C", path, "log", "-n", "300", "--name-only",
                    "--pretty=format:%x1d%H%x1f%an%x1f%aI%x1f%s%x1f%b%x1e"])
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
    commits = []
    for chunk in out.split("\x1d")[1:]:
        head, _, files = chunk.partition("\x1e")
        sha, au, dt, subj, body = head.split("\x1f", 4)
        commits.append(dict(sha=sha, author=au, date=dt[:10], subject=subj, body=body.strip(),
                            files=[f for f in files.split("\n") if f.strip()]))
    base = re.sub(r"(\.git)?/?$", "", src) if src.startswith("http") else ""
    return commits, base


# ---------------------------------------------------------------- classification
ROLE_TOKENS = [
    ("infra", {"requirements", "dockerfile", "docker", "yml", "yaml", "ci", "github", "toml", "cfg"}),
    ("docs", {"md", "docs", "readme", "rst"}),
    ("ml", {"ml", "model", "models", "train", "training", "notebooks", "ipynb", "pkl", "csv", "dataset", "pipeline"}),
    ("frontend", {"js", "jsx", "ts", "tsx", "css", "html", "frontend", "static", "components", "web", "ui"}),
    ("backend", {"api", "server", "routes", "db", "backend", "py", "sql", "app"}),
]


def file_role(path):
    tokens = set(re.split(r"[^a-z0-9]+", path.lower()))
    for role, keys in ROLE_TOKENS:
        if tokens & keys:
            return role
    return "general"


def module_of(path):
    parts = path.split("/")
    return "(root)" if len(parts) == 1 else parts[0]


STRONG = re.compile(r"\b(switch\w*|replac\w*|migrat\w*|adopt\w*|refactor\w*|drop(?:ped)?|chose|decid\w*|introduc\w*|moved? to)\b", re.I)
WHY = re.compile(r"\b(?:because|due to|so that|in order to|since)\s+([^.;\n]+)", re.I)
ALT = re.compile(r"\b(?:instead of|rather than)\s+((?:(?!\b(?:because|since|so that|due to)\b)[^.,;\n])+)", re.I)
OPEN = re.compile(r"\b(todo|fixme|wip|not yet|for now|temporary|hack|incomplete|unfinished)\b", re.I)


# ---------------------------------------------------------------- optional LLM extraction
def llm_decisions(commits):
    """Ask Claude for decisions. Returns None when no API key is configured."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    import requests
    lines = "\n".join(f"{c['sha'][:8]}|{c['author']}|{c['subject']}|{c['body'][:300]}" for c in commits[:60])
    prompt = ("Extract engineering decisions from these commits. Return ONLY a JSON array of objects "
              '{"sha":"8-char sha","decision":"","why":"","alternative":"","explicit":true}. '
              "Set explicit=true only if the commit text itself states the reason or the alternative. "
              "Never invent reasons; use empty strings when unknown.\n\n" + lines)
    r = requests.post("https://api.anthropic.com/v1/messages", timeout=60,
                      headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                      json={"model": os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6"), "max_tokens": 3000,
                            "messages": [{"role": "user", "content": prompt}]})
    r.raise_for_status()
    text = r.json()["content"][0]["text"]
    return json.loads(re.search(r"\[.*\]", text, re.S).group(0))


# ---------------------------------------------------------------- analysis
def analyze(commits, base="", departing=""):
    link = (lambda s: f"{base}/commit/{s}") if base.startswith("http") else (lambda s: "")
    authors = collections.Counter(c["author"] for c in commits)
    mod_auth = collections.defaultdict(collections.Counter)
    mod_roles = collections.defaultdict(collections.Counter)
    co = collections.Counter()
    for c in commits:
        c["modules"] = sorted({module_of(f) for f in c["files"]})
        roles = collections.Counter(file_role(f) for f in c["files"])
        c["role"] = roles.most_common(1)[0][0] if roles else "general"
        for f in c["files"]:
            mod_roles[module_of(f)][file_role(f)] += 1
        for m in c["modules"]:
            mod_auth[m][c["author"]] += 1
        for a, b in itertools.combinations(c["modules"], 2):
            co[(a, b)] += 1
    mrole = {m: r.most_common(1)[0][0] for m, r in mod_roles.items()}

    # dependency graph (module co-change) and centrality
    G = nx.Graph()
    for (a, b), w in co.items():
        G.add_edge(a, b, weight=w)
    cen = nx.degree_centrality(G) if G.number_of_nodes() > 1 else {}
    nodes = [dict(id="p:" + p, label=p, group="person", value=n) for p, n in authors.items()]
    nodes += [dict(id="m:" + m, label=m, group=mrole.get(m, "general"), value=sum(cn.values()),
                   hub=round(cen.get(m, 0), 2)) for m, cn in mod_auth.items()]
    edges = [{"from": "p:" + p, "to": "m:" + m, "value": n, "kind": "owns"}
             for m, cn in mod_auth.items() for p, n in cn.items()]
    edges += [{"from": "m:" + a, "to": "m:" + b, "value": w, "kind": "co-change"} for (a, b), w in co.items()]

    items = []

    def add(**k):
        k.setdefault("status", "pending")
        k.setdefault("roles", [k.get("role", "general")])
        k.setdefault("author", "")
        k["id"] = f"i{len(items) + 1}"
        items.append(k)

    def base_fields(c):
        return dict(sha=c["sha"], url=link(c["sha"]), author=c["author"], date=c["date"],
                    role=c["role"], modules=c["modules"])

    by = {c["sha"][:8]: c for c in commits}
    try:
        rows = llm_decisions(commits)
    except Exception:
        rows = None
    engine = "Claude" if rows is not None else "Rule-based"

    for c in commits:
        text = c["subject"] + "\n" + c["body"]
        if c["subject"].lower().startswith("revert"):
            add(type="conflict", title=c["subject"], confidence="confirmed", alternative="",
                why="This reverts earlier work. Check whether the original decision still stands.", **base_fields(c))
        elif rows is None:
            w, a, s = WHY.search(text), ALT.search(text), STRONG.search(text)
            if s or (w and a):
                add(type="decision", title=c["subject"], why=w.group(1).strip() if w else "",
                    alternative=a.group(1).strip() if a else "",
                    confidence="confirmed" if (w or a) else "inferred", **base_fields(c))
        if OPEN.search(text) and len([i for i in items if i["type"] == "task"]) < 25:
            high = bool(departing) and departing.lower() in c["author"].lower()
            add(type="task", title=c["subject"], why="Marked as unfinished in the commit message.",
                alternative="", priority="high" if high else "normal", confidence="confirmed", **base_fields(c))
    for r in rows or []:
        c = by.get(str(r.get("sha", ""))[:8])
        if c:
            ok = bool(r.get("explicit")) and bool(r.get("why") or r.get("alternative"))
            add(type="decision", title=r.get("decision") or c["subject"], why=r.get("why", ""),
                alternative=r.get("alternative", ""), confidence="confirmed" if ok else "inferred", **base_fields(c))

    for m, cn in mod_auth.items():
        top, n = cn.most_common(1)[0]
        total = sum(cn.values())
        if total >= 3 and n / total >= 0.8:
            add(type="risk", title=f"{m} depends on one person", author=top, role=mrole.get(m, "general"),
                why=f"{top} made {n} of {total} commits that touched {m}. Knowledge is concentrated in one person.",
                alternative="", modules=[m], confidence="confirmed")
    for (a, b), w in co.most_common(10):
        if mrole.get(a) != mrole.get(b) and w >= 2:
            add(type="dependency", title=f"{a} and {b} change together", role=mrole.get(a, "general"),
                roles=[mrole.get(a, "general"), mrole.get(b, "general")], modules=[a, b], alternative="",
                why=f"{w} commits touched both ({mrole.get(a)} and {mrole.get(b)}). Treat the boundary as an interface.",
                confidence="inferred")

    if departing:
        d = departing.lower()
        mine = [i for i in items if not i["author"] or d in i["author"].lower()]
        if any(d in i["author"].lower() for i in items if i["author"]):
            items = mine
    items.sort(key=lambda i: (i.get("priority") != "high",))

    dates = sorted(c["date"] for c in commits)
    return dict(
        summary=dict(commits=len(commits), authors=len(authors), modules=len(mod_auth),
                     first=dates[0], last=dates[-1], engine=engine),
        contributors=[dict(name=p, commits=n, modules=[m for m, _ in sorted(
            ((m, cn[p]) for m, cn in mod_auth.items() if p in cn), key=lambda x: -x[1])[:3]])
            for p, n in authors.most_common()],
        graph=dict(nodes=nodes, edges=edges),
        items=items,
        timeline=[dict(sha=c["sha"][:8], date=c["date"], author=c["author"], title=c["subject"]) for c in commits[:15]],
    )


# ---------------------------------------------------------------- sample project
def demo_commits():
    rows = [
        ("Meera Kulkarni", "2026-11-02", "Update README with run instructions", "", ["README.md", "docs/setup.md"]),
        ("Rohan Iyer", "2026-11-01", "WIP: price chart tooltips", "TODO: mobile layout not yet handled.", ["web/chart.js", "web/style.css"]),
        ("Priya Nair", "2026-10-30", "Revert 'Switch API to GraphQL'", "GraphQL gateway doubled response time on the small server.", ["api/app.py", "api/schema.py"]),
        ("Aarav Mehta", "2026-10-28", "Switch forecasting model from ARIMA to gradient boosting",
         "Using gradient boosting instead of ARIMA because it handles the festival-season spikes that ARIMA kept smoothing out.",
         ["ml/train.py", "ml/features.py", "api/forecast.py"]),
        ("Priya Nair", "2026-10-26", "Switch API to GraphQL", "", ["api/app.py", "api/schema.py", "web/api.js"]),
        ("Rohan Iyer", "2026-10-24", "Add district filter to dashboard", "", ["web/index.html", "web/filters.js", "api/routes.py"]),
        ("Aarav Mehta", "2026-10-21", "Cache features in parquet",
         "Parquet cache so that retraining takes minutes rather than hours. TODO: invalidate cache when the mandi data source changes.",
         ["ml/features.py", "ml/cache.py", "api/forecast.py"]),
        ("Priya Nair", "2026-10-18", "Adopt SQLite for price store",
         "SQLite instead of Postgres because the app runs on one college server and the ops overhead is not worth it.",
         ["api/db.py", "api/app.py", "requirements.txt"]),
        ("Aarav Mehta", "2026-10-15", "Add mandi price scraper", "", ["ml/scraper.py", "ml/features.py"]),
        ("Rohan Iyer", "2026-10-12", "Migrate frontend to vanilla JS modules", "", ["web/api.js", "web/chart.js", "web/index.html"]),
        ("Priya Nair", "2026-10-10", "Add forecast endpoint", "", ["api/forecast.py", "api/app.py", "ml/predict.py"]),
        ("Aarav Mehta", "2026-10-08", "Add baseline ARIMA forecaster", "", ["ml/train.py", "ml/predict.py"]),
        ("Meera Kulkarni", "2026-10-05", "Set up project structure and CI", "", [".github/workflows/ci.yml", "requirements.txt", "README.md"]),
        ("Priya Nair", "2026-10-03", "Add price store schema", "", ["api/db.py", "api/app.py"]),
        ("Aarav Mehta", "2026-10-02", "Add training notebook", "", ["ml/notebooks/explore.ipynb", "ml/train.py"]),
    ]
    return [dict(sha=hashlib.sha1((s + d).encode()).hexdigest(), author=a, date=d, subject=s, body=b, files=f)
            for a, d, s, b, f in rows]
