"""
app.py
------
SmartPark -- a web-based parking management system.

Routes:
  GET  /            Home page -- links to the four sections below
  GET  /board        Live display board (slot availability) -- what drivers see before entry
  GET  /entry         Entry form
  POST /entry         Process vehicle entry
  GET  /exit           Exit form
  POST /exit/quote     Show duration + amount payable for a plate (AJAX-free simple flow)
  POST /exit/pay        Confirm payment and open the barrier
  GET  /admin           Admin: audit log + total collected + rate tiers

Run with:  python app.py
Then open: http://127.0.0.1:5000/
"""

from flask import Flask, render_template, request, redirect, url_for, flash

from database import init_db
from parking_core import ParkingCore

app = Flask(__name__)
app.secret_key = "smartpark-dev-secret"  # fine for a coursework demo

init_db(total_bays=10)
core = ParkingCore()


@app.route("/")
def home():
    return render_template("home.html", available=core.available_count(), total=core.total_bays())


@app.route("/board")
def display_board():
    return render_template(
        "display.html",
        total=core.total_bays(),
        available=core.available_count(),
        occupied=core.occupied_bays(),
        tiers=core.rate_tiers(),
    )


@app.route("/entry", methods=["GET", "POST"])
def entry():
    if request.method == "POST":
        plate = request.form.get("plate", "")
        result = core.vehicle_entry(plate)
        if result["ok"]:
            flash(f"Vehicle {result['plate']} assigned to Bay {result['bay']}.", "success")
        else:
            flash(result["error"], "error")
        return redirect(url_for("entry"))
    return render_template("entry.html", available=core.available_count(), total=core.total_bays())


@app.route("/exit", methods=["GET"])
def exit_form():
    return render_template("exit.html", quote=None)


@app.route("/exit/quote", methods=["POST"])
def exit_quote():
    plate = request.form.get("plate", "")
    quote = core.quote_exit(plate)
    if not quote["ok"]:
        flash(quote["error"], "error")
        return redirect(url_for("exit_form"))
    return render_template("exit.html", quote=quote)


@app.route("/exit/pay", methods=["POST"])
def exit_pay():
    plate = request.form.get("plate", "")
    method = request.form.get("payment_method", "cash")
    result = core.vehicle_exit(plate, method)
    if not result["ok"]:
        flash(result["error"], "error")
        return redirect(url_for("exit_form"))
    flash(
        f"Payment confirmed via {method}. Barrier open for {result['plate']} "
        f"(Ksh {result['fee']:.0f}, {result['duration_minutes']} min).",
        "success",
    )
    return redirect(url_for("display_board"))


@app.route("/admin")
def admin():
    rows, total = core.audit_log()
    return render_template("admin.html", rows=rows, total=total, tiers=core.rate_tiers())


if __name__ == "__main__":
    app.run(debug=True)
