import json
import os
from functools import wraps

from flask import Blueprint, request, jsonify, render_template
import psycopg2
import psycopg2.extras

admin = Blueprint("admin", __name__, url_prefix="/admin")
NEON_DSN = os.environ.get("NEON_DSN", "")
ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", "")


def _get_db():
    return psycopg2.connect(NEON_DSN)

def _exec(conn, sql, params=None):
    is_select = sql.strip().upper().startswith("SELECT")
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params or ())
        if is_select:
            return cur.fetchall()
        conn.commit()
        return None

def _require_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        key = request.headers.get("X-Admin-Key", "")
        if not ADMIN_API_KEY or key != ADMIN_API_KEY:
            return jsonify({"error": "Non autorisé"}), 401
        return f(*args, **kwargs)
    return wrapper

def _audit(action, target, detail=""):
    try:
        conn = _get_db()
        _exec(conn, "INSERT INTO admin_audit_log (action, target, detail) VALUES (%s, %s, %s)", (action, target, detail))
        conn.close()
    except Exception:
        pass

def _init_tables():
    try:
        conn = _get_db()
        _exec(conn, """CREATE TABLE IF NOT EXISTS admin_audit_log (
            id SERIAL PRIMARY KEY, action TEXT NOT NULL,
            target TEXT NOT NULL, detail TEXT DEFAULT '',
            created_at TIMESTAMPTZ DEFAULT NOW())""")
        conn.close()
    except Exception:
        pass

_init_tables()

@admin.route("/")
def admin_index():
    return render_template("admin.html")

@admin.route("/api/partners", methods=["GET"])
@_require_auth
def list_partners():
    conn = _get_db()
    rows = _exec(conn, "SELECT * FROM partners ORDER BY name ASC")
    conn.close()
    return jsonify(rows)

@admin.route("/api/partners", methods=["POST"])
@_require_auth
def create_partner():
    data = request.json
    conn = _get_db()
    try:
        _exec(conn,
            "INSERT INTO partners (name, type, min_amount, max_amount, rate, sectors, docs, description, base_rate, max_rate, countries) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (data["name"], data.get("type", "microfinance"), data.get("min_amount"),
             data.get("max_amount"), data.get("rate", ""), data.get("sectors", []),
             data.get("docs", []), data.get("description", ""),
             data.get("base_rate"), data.get("max_rate"), data.get("countries", ["TG"])))
        _audit("create", f"partner:{data['name']}")
        return jsonify({"ok": True}), 201
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()

@admin.route("/api/partners/<int:partner_id>", methods=["PUT"])
@_require_auth
def update_partner(partner_id):
    data = request.json
    conn = _get_db()
    try:
        sets = []
        params = []
        for col in ("name", "type", "min_amount", "max_amount", "rate", "sectors", "docs", "description", "base_rate", "max_rate", "countries", "active"):
            if col in data:
                sets.append(f"{col} = %s")
                params.append(data[col])
        if not sets:
            return jsonify({"error": "Aucun champ"}), 400
        sets.append("last_verified_at = NOW()")
        params.append(partner_id)
        _exec(conn, f"UPDATE partners SET {', '.join(sets)} WHERE id = %s", params)
        _audit("update", f"partner:{partner_id}", json.dumps(data))
        return jsonify({"ok": True})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()

@admin.route("/api/products", methods=["GET"])
@_require_auth
def list_products():
    conn = _get_db()
    rows = _exec(conn,
        "SELECT pr.*, p.name AS partner_name FROM products pr JOIN partners p ON p.id = pr.partner_id WHERE pr.superseded_at IS NULL ORDER BY p.name, pr.name")
    conn.close()
    return jsonify(rows)

@admin.route("/api/products", methods=["POST"])
@_require_auth
def create_product():
    data = request.json
    conn = _get_db()
    try:
        _exec(conn,
            "INSERT INTO products (partner_id, name, min_amount, max_amount, min_duration_months, max_duration_months, annual_rate, collateral_required, requirements, description, min_income, formal_required, required_guarantees, sector_tags) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (data["partner_id"], data["name"], data.get("min_amount"),
             data.get("max_amount"), data.get("min_duration_months", 1),
             data.get("max_duration_months", 60), data.get("annual_rate"),
             data.get("collateral_required", False), data.get("requirements", []),
             data.get("description", ""), data.get("min_income"),
             data.get("formal_required", False), data.get("required_guarantees", []),
             data.get("sector_tags", [])))
        _audit("create", f"product:{data['name']}")
        return jsonify({"ok": True}), 201
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()

@admin.route("/api/products/<int:product_id>", methods=["PUT"])
@_require_auth
def update_product(product_id):
    data = request.json
    conn = _get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM products WHERE id = %s AND superseded_at IS NULL", (product_id,))
        old = cur.fetchone()
        if not old:
            return jsonify({"error": "Produit introuvable"}), 404
        cur.execute("UPDATE products SET superseded_at = NOW() WHERE id = %s", (product_id,))
        version = (old["version"] or 1) + 1
        cur.execute(
            "INSERT INTO products (partner_id, name, min_amount, max_amount, min_duration_months, max_duration_months, annual_rate, collateral_required, requirements, description, version, min_income, formal_required, required_guarantees, sector_tags) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (data.get("partner_id", old["partner_id"]), data.get("name", old["name"]),
             data.get("min_amount", old["min_amount"]), data.get("max_amount", old["max_amount"]),
             data.get("min_duration_months", old["min_duration_months"]),
             data.get("max_duration_months", old["max_duration_months"]),
             data.get("annual_rate", old["annual_rate"]),
             data.get("collateral_required", old["collateral_required"]),
             data.get("requirements", old["requirements"]),
             data.get("description", old["description"]), version,
             data.get("min_income", old.get("min_income")),
             data.get("formal_required", old.get("formal_required", False)),
             data.get("required_guarantees", old.get("required_guarantees", [])),
             data.get("sector_tags", old.get("sector_tags", []))))
        conn.commit()
        _audit("update", f"product:{product_id}→v{version}", json.dumps(data))
        return jsonify({"ok": True, "new_version": version})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()

@admin.route("/api/stale")
@_require_auth
def stale_products():
    conn = _get_db()
    rows = _exec(conn,
        "SELECT pr.id, pr.name, p.name AS partner_name, pr.last_verified_at FROM products pr JOIN partners p ON p.id = pr.partner_id WHERE pr.superseded_at IS NULL AND (pr.last_verified_at IS NULL OR pr.last_verified_at < NOW() - INTERVAL '30 days') ORDER BY pr.last_verified_at NULLS FIRST")
    conn.close()
    return jsonify(rows)

@admin.route("/api/audit")
@_require_auth
def audit_log():
    conn = _get_db()
    rows = _exec(conn, "SELECT * FROM admin_audit_log ORDER BY created_at DESC LIMIT 100")
    conn.close()
    return jsonify(rows)
