"""RideLite: a deliberately buggy ride-hailing demo app used to benchmark Phalanx.

DO NOT DEPLOY. Every bug here is planted on purpose; ground truth lives in
demo_app/planted_bugs.json, which the agent never reads (only the benchmark does).

Seed accounts: alice/alice123 (rider), bob/bob123 (rider),
               dave/dave123 (driver), root/root123 (admin)
"""
from __future__ import annotations

import itertools
import os

from flask import Flask, jsonify, make_response, redirect, request, session

app = Flask(__name__)
app.secret_key = os.getenv("RIDELITE_SECRET", "dev-only-not-a-secret")

USERS = {
    "alice": {"password": "alice123", "role": "rider", "email": "alice@example.test"},
    "bob": {"password": "bob123", "role": "rider", "email": "bob@example.test"},
    "dave": {"password": "dave123", "role": "driver", "email": "dave@example.test"},
    "root": {"password": "root123", "role": "admin", "email": "root@example.test"},
}
RIDES: dict[int, dict] = {}
_ids = itertools.count(1)


def reset() -> None:
    RIDES.clear()
    global _ids
    _ids = itertools.count(1)


def me():
    return session.get("user")


def page(title: str, body: str) -> str:
    user = me()
    role = USERS[user]["role"] if user else None
    nav = [
        '<a href="/">Home</a>',
        '<a href="/estimate">Fare estimate</a>',
        '<a href="/search">Search</a>',
        '<a href="/help">Help</a>',  # B1: /help does not exist -> 404 from a visible nav link
    ]
    if user:
        nav += [
            '<a href="/book">Book a ride</a>',
            '<a href="/rides">My rides</a>',
            '<a href="/profile">Profile</a>',
        ]
        if role == "driver":
            nav.append('<a href="/driver/queue">Driver queue</a>')
        if role == "admin":
            nav.append('<a href="/admin">Admin</a>')
        nav.append('<a href="/logout">Log out</a>')
    else:
        nav.append('<a href="/login">Log in</a>')
    return f"""<!doctype html>
<html><head><title>{title} · RideLite</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:720px;margin:2rem auto;padding:0 1rem}}
nav a{{margin-right:1rem}} .err{{color:#b00020}} .ok{{color:#0a7}} table{{border-collapse:collapse;width:100%}}
td,th{{border:1px solid #ddd;padding:.4rem}} .badge{{background:#eee;padding:.1rem .4rem;border-radius:4px}}
</style></head>
<body>
<nav>{" ".join(nav)}</nav>
<hr>
<h1>{title}</h1>
{body}
</body></html>"""


@app.get("/")
def home():
    user = me()
    if not user:
        return page("Welcome", "<p>RideLite — book a ride in three clicks.</p><p><a href='/login'>Log in</a> to start.</p>")
    return page(
        f"Hi {user}",
        f"<p>Role: <span class='badge'>{USERS[user]['role']}</span></p>"
        "<ul><li><a href='/book'>Book a ride</a></li><li><a href='/rides'>My rides</a></li></ul>",
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return page(
            "Log in",
            "<form method='post'>"
            "<label>Username <input name='username' required></label><br><br>"
            "<label>Password <input name='password' type='password' required></label><br><br>"
            "<button type='submit'>Log in</button></form>"
            "<p>Demo: alice/alice123 · bob/bob123 · dave/dave123 · root/root123</p>",
        )
    u = request.form.get("username", "")
    p = request.form.get("password", "")
    if u in USERS and USERS[u]["password"] == p:
        session["user"] = u
        return redirect("/")
    return page("Log in", "<p class='err'>Invalid credentials</p><a href='/login'>Try again</a>"), 401


@app.get("/logout")
def logout():
    session.clear()
    return redirect("/")


@app.route("/book", methods=["GET", "POST"])
def book():
    if not me():
        return redirect("/login")
    if request.method == "GET":
        return page(
            "Book a ride",
            "<form method='post'>"
            "<label>Pickup <input name='pickup' required placeholder='Airport'></label><br><br>"
            "<label>Dropoff <input name='dropoff' required placeholder='Downtown'></label><br><br>"
            "<button type='submit'>Request ride</button></form>",
        )
    rid = next(_ids)
    RIDES[rid] = {
        "id": rid,
        "owner": me(),
        "pickup": request.form.get("pickup", ""),
        "dropoff": request.form.get("dropoff", ""),
        "status": "requested",
        "driver": None,
        "fare": 12.5,
    }
    return redirect(f"/rides/{rid}")


@app.get("/rides")
def rides():
    if not me():
        return redirect("/login")
    # B2: IDOR in list — returns EVERY ride, not just the caller's
    rows = "".join(
        f"<tr><td><a href='/rides/{r['id']}'>{r['id']}</a></td>"
        f"<td>{r['owner']}</td><td>{r['pickup']} → {r['dropoff']}</td>"
        f"<td>{r['status']}</td><td>${r['fare']:.2f}</td></tr>"
        for r in RIDES.values()
    )
    return page(
        "My rides",
        f"<table><tr><th>ID</th><th>Owner</th><th>Route</th><th>Status</th><th>Fare</th></tr>{rows or '<tr><td colspan=5>No rides yet</td></tr>'}</table>",
    )


@app.get("/rides/<int:rid>")
def ride_detail(rid: int):
    if not me():
        return redirect("/login")
    r = RIDES.get(rid)
    if not r:
        return page("Not found", "<p class='err'>Ride missing</p>"), 404
    # B3: IDOR on detail — no ownership check
    return page(
        f"Ride #{rid}",
        f"<p>Owner: <b>{r['owner']}</b></p>"
        f"<p>{r['pickup']} → {r['dropoff']}</p>"
        f"<p>Status: {r['status']} · Fare: ${r['fare']:.2f}</p>"
        f"<form method='post' action='/rides/{rid}/cancel'><button>Cancel ride</button></form>"
        f"<form method='post' action='/rides/{rid}/tip'>"
        f"<label>Tip $<input name='amount' type='number' step='0.01' value='2'></label> "
        f"<button>Add tip</button></form>",
    )


@app.post("/rides/<int:rid>/cancel")
def cancel(rid: int):
    if not me():
        return redirect("/login")
    r = RIDES.get(rid)
    if not r:
        return page("Not found", "<p class='err'>Ride missing</p>"), 404
    # B4: any logged-in user can cancel anyone else's ride
    r["status"] = "cancelled"
    return redirect(f"/rides/{rid}")


@app.post("/rides/<int:rid>/tip")
def tip(rid: int):
    if not me():
        return redirect("/login")
    r = RIDES.get(rid)
    if not r:
        return page("Not found", "<p class='err'>Ride missing</p>"), 404
    try:
        amount = float(request.form.get("amount", "0"))
    except ValueError:
        amount = 0.0
    # B5: negative tip accepted — fare can go negative
    r["fare"] = r["fare"] + amount
    return redirect(f"/rides/{rid}")


@app.get("/admin")
def admin():
    # B6: missing auth check — any visitor (even logged out) can open /admin
    rows = "".join(
        f"<tr><td>{u}</td><td>{info['role']}</td><td>{info['email']}</td><td>{info['password']}</td></tr>"
        for u, info in USERS.items()
    )
    # B7: plaintext passwords rendered in the admin table
    return page(
        "Admin panel",
        f"<p>Users ({len(USERS)})</p>"
        f"<table><tr><th>User</th><th>Role</th><th>Email</th><th>Password</th></tr>{rows}</table>"
        f"<p>Rides in memory: {len(RIDES)}</p>",
    )


@app.get("/estimate")
def estimate():
    # B8: reflected XSS — `q` is echoed without escaping
    q = request.args.get("q", "")
    return page(
        "Fare estimate",
        f"<form method='get'><label>Where to? <input name='q' value=\"{q}\"></label> "
        f"<button>Estimate</button></form>"
        + (f"<p>Estimated fare for <b>{q}</b>: $14.00</p>" if q else ""),
    )


@app.get("/search")
def search():
    # B9: SQL-injection-shaped error when input contains a quote (fake DB error page)
    q = request.args.get("q", "")
    if "'" in q or ";" in q:
        return (
            page(
                "Database error",
                f"<pre class='err'>sqlite3.OperationalError: near \"{q}\": syntax error\n"
                f"Query: SELECT * FROM places WHERE name LIKE '%{q}%'</pre>",
            ),
            500,
        )
    hits = [p for p in ("Airport", "Downtown", "University", "Mall") if q.lower() in p.lower()] if q else []
    lis = "".join(f"<li>{h}</li>" for h in hits) or "<li>No matches</li>"
    return page(
        "Search places",
        f"<form method='get'><input name='q' value='{q}'><button>Search</button></form><ul>{lis}</ul>",
    )


@app.get("/profile")
def profile():
    if not me():
        return redirect("/login")
    u = me()
    # B10: open redirect on ?next= — used after "save"
    nxt = request.args.get("next", "/profile")
    if request.args.get("saved"):
        return redirect(nxt)
    return page(
        "Profile",
        f"<p>Username: {u}</p><p>Email: {USERS[u]['email']}</p>"
        f"<form method='get'><input type='hidden' name='saved' value='1'>"
        f"<input type='hidden' name='next' value='{nxt}'>"
        f"<button>Save (noop)</button></form>",
    )


@app.get("/driver/queue")
def driver_queue():
    if not me() or USERS[me()]["role"] != "driver":
        return page("Forbidden", "<p class='err'>Drivers only</p>"), 403
    open_rides = [r for r in RIDES.values() if r["status"] == "requested"]
    rows = "".join(
        f"<tr><td>{r['id']}</td><td>{r['pickup']} → {r['dropoff']}</td>"
        f"<td><form method='post' action='/driver/claim/{r['id']}'><button>Claim</button></form></td></tr>"
        for r in open_rides
    )
    return page("Driver queue", f"<table><tr><th>ID</th><th>Route</th><th></th></tr>{rows or '<tr><td colspan=3>Empty</td></tr>'}</table>")


@app.post("/driver/claim/<int:rid>")
def claim(rid: int):
    if not me() or USERS[me()]["role"] != "driver":
        return page("Forbidden", "<p class='err'>Drivers only</p>"), 403
    r = RIDES.get(rid)
    if r and r["status"] == "requested":
        r["status"] = "claimed"
        r["driver"] = me()
    return redirect("/driver/queue")


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "rides": len(RIDES)})


@app.get("/api/rides/<int:rid>")
def api_ride(rid: int):
    # B11: unauthenticated JSON IDOR — no session check at all
    r = RIDES.get(rid)
    if not r:
        return jsonify({"error": "not found"}), 404
    return jsonify(r)


@app.after_request
def cookies(resp):
    # B12: session cookie set without Secure / HttpOnly flags on a forged secondary cookie
    if me() and "debug_token" not in request.cookies:
        resp.set_cookie("debug_token", me() + "-token", httponly=False, samesite=None)
    return resp


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "5055")), debug=False)
