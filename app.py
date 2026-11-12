import mimetypes
import os
import secrets
import sqlite3
import uuid
from datetime import date, datetime

from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   send_from_directory, session, url_for)
from PIL import Image

import ai

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "lostfound.db")
UPLOADS = os.path.join(BASE, "uploads")
ADMIN_PIN = os.environ.get("ADMIN_PIN", "1234")
os.makedirs(UPLOADS, exist_ok=True)

# Windows reads MIME types from the registry, which sometimes maps .css/.svg
# to text/plain; browsers then refuse to apply the stylesheet.
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("application/javascript", ".js")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "hackathon-dev-key")
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB photos

# Campus places grouped into zones, so "nearby" locations still score.
LOCATIONS = {
    "Academic Block": ["Main Building", "Library", "Computer Lab", "Lecture Hall Complex",
                       "Physics/Chem Labs", "Exam Hall"],
    "Food & Hangout": ["Canteen", "Food Court", "Juice Shop", "Student Activity Centre"],
    "Sports": ["Gym", "Football Ground", "Basketball Court", "Indoor Stadium"],
    "Hostels": ["Boys Hostel", "Girls Hostel", "Hostel Mess"],
    "Transit": ["Main Gate", "Parking", "College Bus", "Auditorium"],
}
ZONE = {loc: z for z, locs in LOCATIONS.items() for loc in locs}


def zone_of(loc):
    return ZONE.get(loc, loc)


# ---------------------------------------------------------------- database
def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_):
    d = g.pop("db", None)
    if d:
        d.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL CHECK (kind IN ('lost','found')),
  title TEXT NOT NULL,
  category TEXT NOT NULL,
  color TEXT,
  description TEXT NOT NULL,
  ai_description TEXT,
  location TEXT NOT NULL,
  item_date TEXT NOT NULL,
  photo TEXT,
  contact_name TEXT NOT NULL,
  contact TEXT NOT NULL,
  at_desk INTEGER DEFAULT 0,
  status TEXT DEFAULT 'open',
  owner_code TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS matches (
  lost_id INTEGER, found_id INTEGER, score INTEGER, reason TEXT, engine TEXT,
  PRIMARY KEY (lost_id, found_id)
);
"""


def init_db():
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA)
    con.close()


# ---------------------------------------------------------------- matching
def run_matching(item_id):
    item = dict(db().execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone())
    other = "found" if item["kind"] == "lost" else "lost"
    cands = [dict(r) for r in db().execute(
        "SELECT * FROM items WHERE kind=? AND status='open'", (other,))]
    found_matches, engine = ai.find_matches(item, cands, zone_of)
    col = "lost_id" if item["kind"] == "lost" else "found_id"
    db().execute(f"DELETE FROM matches WHERE {col}=?", (item_id,))
    for m in found_matches:
        lost_id, found_id = (item_id, m["id"]) if item["kind"] == "lost" else (m["id"], item_id)
        db().execute("INSERT OR REPLACE INTO matches VALUES (?,?,?,?,?)",
                     (lost_id, found_id, m["score"], m["reason"], engine))
    db().commit()
    return engine


def matches_for(item):
    if item["kind"] == "lost":
        q = """SELECT i.*, m.score, m.reason, m.engine FROM matches m
               JOIN items i ON i.id=m.found_id WHERE m.lost_id=? ORDER BY m.score DESC"""
    else:
        q = """SELECT i.*, m.score, m.reason, m.engine FROM matches m
               JOIN items i ON i.id=m.lost_id WHERE m.found_id=? ORDER BY m.score DESC"""
    return db().execute(q, (item["id"],)).fetchall()


# ---------------------------------------------------------------- routes
@app.context_processor
def inject():
    return {"ai_enabled": ai.AI_ENABLED, "is_admin": session.get("admin", False),
            "categories": ai.CATEGORIES, "locations": LOCATIONS}


@app.route("/")
def index():
    kind = request.args.get("kind", "")
    cat = request.args.get("category", "")
    q = request.args.get("q", "").strip()
    show = request.args.get("show", "open")
    sql, args = "SELECT * FROM items WHERE 1=1", []
    if show == "open":
        sql += " AND status='open'"
    if kind in ("lost", "found"):
        sql += " AND kind=?"; args.append(kind)
    if cat:
        sql += " AND category=?"; args.append(cat)
    if q:
        sql += " AND (title LIKE ? OR description LIKE ? OR ai_description LIKE ? OR location LIKE ?)"
        args += [f"%{q}%"] * 4
    items = db().execute(sql + " ORDER BY created_at DESC", args).fetchall()
    match_counts = {r[0]: r[1] for r in db().execute(
        """SELECT id, COUNT(*) FROM (
             SELECT lost_id id FROM matches WHERE score>=50
             UNION ALL SELECT found_id id FROM matches WHERE score>=50) GROUP BY id""")}
    stats = db().execute(
        """SELECT SUM(kind='lost' AND status='open'), SUM(kind='found' AND status='open'),
                  SUM(status='returned') FROM items""").fetchone()
    return render_template("index.html", items=items, match_counts=match_counts,
                           stats=stats, f={"kind": kind, "category": cat, "q": q, "show": show})


@app.route("/report/<kind>", methods=["GET", "POST"])
def report(kind):
    if kind not in ("lost", "found"):
        abort(404)
    if request.method == "GET":
        return render_template("report.html", kind=kind, today=date.today().isoformat())

    form = request.form
    title = form.get("title", "").strip()
    description = form.get("description", "").strip()
    photo_name, tags = None, None

    file = request.files.get("photo")
    if file and file.filename:
        photo_name = f"{uuid.uuid4().hex}.jpg"
        path = os.path.join(UPLOADS, photo_name)
        try:
            img = Image.open(file.stream).convert("RGB")
            img.thumbnail((1200, 1200))  # keep uploads + AI calls small
            img.save(path, "JPEG", quality=85)
        except Exception:
            flash("That file doesn't look like an image.", "error")
            return redirect(request.url)
        tags = ai.describe_photo(path, f"{title}. {description}")

    if not title and not tags:
        flash("Add a title or a photo so others can recognise the item.", "error")
        return redirect(request.url)

    category = form.get("category") or (tags or {}).get("category") or "Other"
    if category not in ai.CATEGORIES:
        category = "Other"
    ai_desc = None
    if tags:
        ai_desc = f"{tags['description']} Brand: {tags['brand'] or 'unknown'}."
    code = secrets.token_hex(3).upper()
    cur = db().execute(
        """INSERT INTO items (kind,title,category,color,description,ai_description,location,
           item_date,photo,contact_name,contact,at_desk,owner_code,created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (kind, title or tags["title"], category,
         form.get("color", "").strip() or (tags or {}).get("color", ""),
         description or (tags or {}).get("description", ""), ai_desc,
         form.get("location") or "Main Building", form.get("item_date") or date.today().isoformat(),
         photo_name, form.get("contact_name", "").strip() or "Anonymous",
         form.get("contact", "").strip() or "Security desk",
         1 if form.get("at_desk") else 0, code, datetime.now().isoformat(timespec="seconds")))
    db().commit()
    run_matching(cur.lastrowid)
    session.setdefault("my_codes", {})[str(cur.lastrowid)] = code
    session.modified = True
    flash(f"Posted! Your item code is {code} — keep it to mark the item as returned.", "ok")
    return redirect(url_for("item", item_id=cur.lastrowid))


@app.route("/item/<int:item_id>")
def item(item_id):
    it = db().execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if not it:
        abort(404)
    mine = session.get("my_codes", {}).get(str(item_id)) == it["owner_code"]
    return render_template("item.html", it=it, matches=matches_for(it), mine=mine)


@app.post("/item/<int:item_id>/rematch")
def rematch(item_id):
    engine = run_matching(item_id)
    flash(f"Matches refreshed using {'Claude AI' if engine == 'claude' else 'the local matcher'}.", "ok")
    return redirect(url_for("item", item_id=item_id))


@app.post("/item/<int:item_id>/resolve")
def resolve(item_id):
    it = db().execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if not it:
        abort(404)
    code = request.form.get("code", "").strip().upper()
    if not (session.get("admin") or code == it["owner_code"]):
        flash("Wrong item code. Only the poster or security staff can close this.", "error")
        return redirect(url_for("item", item_id=item_id))
    ids = [item_id]
    other = request.form.get("matched_with")
    if other and other.isdigit():
        ids.append(int(other))
    db().executemany("UPDATE items SET status='returned' WHERE id=?", [(i,) for i in ids])
    db().commit()
    flash("Marked as returned. Nice work! 🎉", "ok")
    return redirect(url_for("item", item_id=item_id))


@app.route("/desk", methods=["GET", "POST"])
def desk():
    if request.method == "POST":
        if request.form.get("pin") == ADMIN_PIN:
            session["admin"] = True
        else:
            flash("Wrong PIN.", "error")
        return redirect(url_for("desk"))
    if not session.get("admin"):
        return render_template("desk_login.html")
    held = db().execute(
        "SELECT * FROM items WHERE kind='found' AND at_desk=1 AND status='open' ORDER BY created_at").fetchall()
    strong = db().execute(
        """SELECT m.*, l.title lost_title, l.contact_name, l.contact, f.title found_title,
                  f.at_desk FROM matches m JOIN items l ON l.id=m.lost_id
           JOIN items f ON f.id=m.found_id
           WHERE m.score>=60 AND l.status='open' AND f.status='open'
           ORDER BY m.score DESC""").fetchall()
    return render_template("desk.html", held=held, strong=strong)


@app.route("/logout")
def logout():
    session.pop("admin", None)
    return redirect(url_for("index"))


@app.route("/uploads/<path:name>")
def uploads(name):
    return send_from_directory(UPLOADS, name)


init_db()

if __name__ == "__main__":
    print("AI matching:", "Claude" if ai.AI_ENABLED else "local fallback (set ANTHROPIC_API_KEY for Claude)")
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
