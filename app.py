"""ContinuAI backend. Run: python app.py"""
import json, os, sqlite3, subprocess, time
from flask import Flask, jsonify, request, send_from_directory
from analyzer import analyze, load_commits

app = Flask(__name__, static_folder="static")
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "continuai.db")


def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


with db() as _c:
    _c.executescript("""
    create table if not exists h(id integer primary key, source text, departing text, status text, created text, data text);
    create table if not exists log(id integer primary key, hid integer, ts text, actor text, kind text, detail text, snap text);
    """)

now = lambda: time.strftime("%Y-%m-%d %H:%M:%S")


def get(hid):
    with db() as c:
        row = c.execute("select * from h where id=?", (hid,)).fetchone()
    if not row:
        raise LookupError("Handover not found.")
    return dict(row, data=json.loads(row["data"]))


def save(hid, data, actor, kind, detail, status=None):
    with db() as c:
        c.execute("update h set data=?, status=coalesce(?, status) where id=?", (json.dumps(data), status, hid))
        c.execute("insert into log(hid,ts,actor,kind,detail,snap) values(?,?,?,?,?,?)",
                  (hid, now(), actor, kind, detail, json.dumps(data) if kind == "version" else None))


@app.errorhandler(LookupError)
def _nf(e):
    return jsonify(error=str(e)), 404


@app.get("/")
def index():
    return send_from_directory("static", "index.html")


@app.post("/api/analyze")
def api_analyze():
    j = request.get_json(force=True)
    src, dep = (j.get("source") or "").strip(), (j.get("departing") or "").strip()
    if not src:
        return jsonify(error="Enter a repository to analyze."), 400
    try:
        commits, base = load_commits(src)
        if not commits:
            raise ValueError("No commits found in that repository.")
        data = analyze(commits, base, dep)
    except FileNotFoundError:
        return jsonify(error="Git is not installed or not on your PATH."), 400
    except (ValueError, subprocess.TimeoutExpired) as e:
        return jsonify(error=str(e) if isinstance(e, ValueError) else "Cloning timed out."), 400
    with db() as c:
        hid = c.execute("insert into h(source,departing,status,created,data) values(?,?,?,?,?)",
                        (src, dep, "draft", now(), json.dumps(data))).lastrowid
    save(hid, data, "System", "event", f"Analyzed {data['summary']['commits']} commits from {src}")
    return jsonify(id=hid)


@app.get("/api/h")
def api_list():
    with db() as c:
        rows = c.execute("select id,source,status,created from h order by id desc limit 8").fetchall()
    return jsonify([dict(r) for r in rows])


@app.get("/api/h/<int:hid>")
def api_get(hid):
    h = get(hid)
    return jsonify(source=h["source"], status=h["status"], departing=h["departing"], data=h["data"])


@app.post("/api/h/<int:hid>/item")
def api_item(hid):
    j = request.get_json(force=True)
    h = get(hid)
    if h["status"] == "published":
        return jsonify(error="This handover is published and can no longer be edited."), 409
    item = next((i for i in h["data"]["items"] if i["id"] == j.get("item_id")), None)
    if not item:
        return jsonify(error="Item not found."), 404
    act, who = j.get("action"), (j.get("actor") or "Reviewer")[:60]
    if act in ("approve", "reject", "reset"):
        item["status"] = {"approve": "approved", "reject": "rejected", "reset": "pending"}[act]
        note = {"approve": "Approved", "reject": "Rejected", "reset": "Reset to pending"}[act] + f": {item['title']}"
    elif act == "edit":
        for f in ("title", "why", "alternative"):
            if f in j:
                item[f] = str(j[f])[:600]
        item["edited"] = True
        note = f"Edited: {item['title']}"
    else:
        return jsonify(error="Unknown action."), 400
    save(hid, h["data"], who, "version", note)
    return jsonify(h["data"])


@app.post("/api/h/<int:hid>/publish")
def api_publish(hid):
    h = get(hid)
    n = sum(i["status"] == "approved" for i in h["data"]["items"])
    if not n:
        return jsonify(error="Approve at least one item before publishing."), 400
    who = (request.get_json(force=True).get("actor") or "Reviewer")[:60]
    save(hid, h["data"], who, "event", f"Published handover with {n} approved items", status="published")
    return jsonify(ok=True)


@app.get("/api/h/<int:hid>/view")
def api_view(hid):
    h = get(hid)
    if h["status"] != "published":
        return jsonify(error="Publish the handover to see role views."), 409
    role = request.args.get("role", "lead")
    d = h["data"]
    items = [i for i in d["items"] if i["status"] == "approved" and (role == "lead" or role in i["roles"])]
    nodes, edges = d["graph"]["nodes"], d["graph"]["edges"]
    if role != "lead":
        mine = {n["id"] for n in nodes if n["group"] == role}
        edges = [e for e in edges if e["from"] in mine or e["to"] in mine]
        keep = {e["from"] for e in edges} | {e["to"] for e in edges} | mine
        nodes = [n for n in nodes if n["id"] in keep]
    return jsonify(items=items, graph=dict(nodes=nodes, edges=edges))


@app.post("/api/h/<int:hid>/ack")
def api_ack(hid):
    j = request.get_json(force=True)
    name = (j.get("name") or "").strip()[:60]
    if not name:
        return jsonify(error="Enter your name to confirm receipt."), 400
    h = get(hid)
    save(hid, h["data"], name, "event", f"Received the {j.get('role', 'lead')} handover")
    return jsonify(ok=True)


@app.get("/api/h/<int:hid>/log")
def api_log(hid):
    with db() as c:
        rows = c.execute("select ts,actor,kind,detail from log where hid=? order by id desc", (hid,)).fetchall()
    return jsonify([dict(r) for r in rows])


if __name__ == "__main__":
    app.run(port=int(os.environ.get("PORT", 5000)), debug=False)
