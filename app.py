import json
import os
import sqlite3
import uuid
from datetime import datetime

from flask import Flask, render_template, request, jsonify, session, send_from_directory

from credo_ai import (
    score_from_answers,
    build_first_question,
    build_next_question,
    extract_document_fields,
    generate_code,
)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "credo-dev-2026")

DB_PATH = os.environ.get("CREDO_DB_PATH", "/tmp/credo.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            phone TEXT,
            plan TEXT DEFAULT '5000',
            status TEXT DEFAULT 'payment_wait',
            code TEXT,
            payment_ref TEXT,
            payment_verified INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            completed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            role TEXT,
            question TEXT,
            answer TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            doc_type TEXT,
            storage_url TEXT,
            extracted_json TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT UNIQUE,
            score INTEGER,
            risk TEXT,
            max_amount INTEGER,
            partners TEXT,
            missing_docs TEXT,
            tips TEXT,
            code TEXT UNIQUE,
            loan_amount INTEGER,
            analysis TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        -- Purge anciennes donnees de test (fallback)
        DELETE FROM results WHERE score > 600;
        DELETE FROM sessions WHERE status = 'completed';
    """)
    conn.commit()
    conn.close()


init_db()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/chat/new")
def chat_new():
    return render_template("chat_new.html")


@app.route("/chat/<session_id>")
def chat(session_id):
    conn = get_db()
    s = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    conn.close()
    if not s:
        return render_template("chat_new.html")
    plan = s["plan"]
    return render_template("chat.html", session_id=session_id, plan=plan)


@app.route("/api/session/start", methods=["POST"])
def start_session():
    data = request.json
    phone = data.get("phone", "").strip()
    plan = data.get("plan", "5000")

    if not phone or len(phone) < 6:
        return jsonify({"error": "Numero invalide"}), 400

    session_id = str(uuid.uuid4())[:8]
    conn = get_db()
    conn.execute(
        "INSERT INTO sessions (id, phone, plan, status) VALUES (?, ?, ?, 'chat_active')",
        (session_id, phone, plan),
    )
    conn.commit()
    conn.close()

    try:
        first_q = build_first_question()
    except Exception as e:
        return jsonify({"error": f"Credo IA indisponible. Capture d'ecran avec ta requete a it@originafrika.online"}), 503

    conn = get_db()
    conn.execute(
        "INSERT INTO messages (session_id, role, question) VALUES (?, 'ia', ?)",
        (session_id, first_q),
    )
    conn.commit()
    conn.close()

    return jsonify({"session_id": session_id, "first_question": first_q})


@app.route("/api/chat/<session_id>/message", methods=["POST"])
def chat_message(session_id):
    data = request.json
    answer = data.get("answer", "").strip()

    if not answer:
        return jsonify({"error": "Reponse vide"}), 400

    conn = get_db()
    session_row = conn.execute(
        "SELECT * FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if not session_row:
        conn.close()
        return jsonify({"error": "Session invalide"}), 404

    # Sauvegarde la derniere question et reponse
    last_msg = conn.execute(
        "SELECT question FROM messages WHERE session_id = ? AND role = 'ia' ORDER BY id DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    last_question = last_msg["question"] if last_msg else "Question"

    conn.execute(
        "INSERT INTO messages (session_id, role, question, answer) VALUES (?, 'user', ?, ?)",
        (session_id, last_question, answer),
    )
    conn.commit()

    # Recupere tout l'historique
    messages = conn.execute(
        "SELECT question, answer FROM messages WHERE session_id = ? AND role = 'user' ORDER BY id",
        (session_id,),
    ).fetchall()

    answers = [{"q": m["question"], "a": m["answer"]} for m in messages]

    # Prochaine question via IA (decide elle-meme si assez d'infos)
    try:
        next_q = build_next_question(answers)
    except Exception as e:
        conn.close()
        return jsonify({"error": "Credo IA indisponible. Capture d'ecran avec ta requete a it@originafrika.online"}), 503

    conn.execute(
        "INSERT INTO messages (session_id, role, question) VALUES (?, 'ia', ?)",
        (session_id, next_q),
    )
    conn.commit()
    conn.close()

    if next_q == "DONE":
        return jsonify({"done": True})
    return jsonify({"question": next_q, "done": False})


@app.route("/api/chat/<session_id>/analyze", methods=["POST"])
def analyze(session_id):
    conn = get_db()
    session_row = conn.execute(
        "SELECT * FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if not session_row:
        conn.close()
        return jsonify({"error": "Session invalide"}), 404

    # Recupere les reponses
    messages = conn.execute(
        "SELECT question, answer FROM messages WHERE session_id = ? AND role = 'user' ORDER BY id",
        (session_id,),
    ).fetchall()

    answers = [{"q": m["question"], "a": m["answer"]} for m in messages]

    # Scoring via IA
    try:
        result = score_from_answers(answers)
    except Exception as e:
        conn.close()
        return jsonify({"error": "Credo IA indisponible. Capture d'ecran avec ta requete a it@originafrika.online"}), 503

    # Genere code de referral si plan complet
    code = None
    plan = session_row["plan"]
    if plan == "5000":
        code = generate_code()

    # Sauvegarde
    conn.execute(
        """INSERT OR REPLACE INTO results
        (session_id, score, risk, max_amount, partners, missing_docs, tips, code, analysis)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            session_id,
            result["score"],
            result["risk"],
            result["max_amount"],
            json.dumps(result.get("recommended_partners", [])),
            json.dumps(result.get("missing_documents", [])),
            json.dumps(result.get("improvement_tips", [])),
            code,
            result.get("analysis", ""),
        ),
    )
    conn.execute(
        "UPDATE sessions SET status = 'completed', code = ?, completed_at = datetime('now') WHERE id = ?",
        (code, session_id),
    )
    conn.commit()
    conn.close()

    return jsonify({
        "score": result["score"],
        "risk": result["risk"],
        "max_amount": result["max_amount"],
        "partners": result.get("recommended_partners", []),
        "missing_documents": result.get("missing_documents", []),
        "tips": result.get("improvement_tips", []),
        "analysis": result.get("analysis", ""),
        "code": code,
        "plan": plan,
    })


@app.route("/api/chat/<session_id>/result")
def get_result(session_id):
    conn = get_db()
    result = conn.execute(
        "SELECT * FROM results WHERE session_id = ?", (session_id,)
    ).fetchone()
    session_row = conn.execute(
        "SELECT * FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    conn.close()

    if not result:
        return jsonify({"error": "Analyse non trouvee"}), 404

    return jsonify({
        "score": result["score"],
        "risk": result["risk"],
        "max_amount": result["max_amount"],
        "partners": json.loads(result["partners"]),
        "missing_documents": json.loads(result["missing_docs"]),
        "tips": json.loads(result["tips"]),
        "code": result["code"],
        "analysis": result["analysis"],
        "plan": session_row["plan"] if session_row else "2500",
    })


@app.route("/api/documents/upload/<session_id>", methods=["POST"])
def upload_document(session_id):
    if "file" not in request.files:
        return jsonify({"error": "Aucun fichier"}), 400

    file = request.files["file"]
    doc_type = request.form.get("doc_type", "other")

    if file.filename == "":
        return jsonify({"error": "Fichier vide"}), 400

    # Stockage local /tmp pour MVP (Vercel Blob plus tard)
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else "jpg"
    doc_id = str(uuid.uuid4())[:8]
    filename = f"{session_id}_{doc_id}.{ext}"
    filepath = os.path.join("/tmp", filename)
    file.save(filepath)

    storage_url = f"/uploads/{filename}"

    conn = get_db()
    conn.execute(
        "INSERT INTO documents (session_id, doc_type, storage_url) VALUES (?, ?, ?)",
        (session_id, doc_type, storage_url),
    )
    conn.commit()
    conn.close()

    return jsonify({"document_id": doc_id, "storage_url": storage_url})


@app.route("/verify/<code>")
def verify_code(code):
    """Page partenaire pour verifier un code"""
    conn = get_db()
    result = conn.execute(
        """SELECT r.score, r.max_amount, r.risk, r.code, r.partners,
                  r.missing_docs, r.tips, r.created_at,
                  s.phone, s.status as session_status
        FROM results r JOIN sessions s ON r.session_id = s.id
        WHERE r.code = ?""",
        (code,),
    ).fetchone()
    conn.close()

    if not result:
        return render_template("verify.html", code=code, valid=False)

    partners_data = json.loads(result["partners"]) if result["partners"] else []
    missing_docs = json.loads(result["missing_docs"]) if result["missing_docs"] else []
    tips_data = json.loads(result["tips"]) if result["tips"] else []

    return render_template("verify.html",
        code=code, valid=True,
        score=result["score"],
        max_amount=result["max_amount"],
        risk=result["risk"],
        partners=partners_data,
        missing_docs=missing_docs,
        tips=tips_data,
        phone=result["phone"][:3] + "XX" + result["phone"][-2:],
        created_at=result["created_at"],
    )


@app.route("/api/verify/<code>/update", methods=["POST"])
def update_referral(code):
    """Partenaire confirme le statut (contacte, approuve, funded, rejete)"""
    data = request.json
    new_status = data.get("status")
    loan_amount = data.get("loan_amount")

    valid_statuses = ["contacted", "approved", "funded", "rejected"]
    if new_status not in valid_statuses:
        return jsonify({"error": "Statut invalide"}), 400

    conn = get_db()
    conn.execute(
        "UPDATE sessions SET status = ?, completed_at = datetime('now') WHERE code = ?",
        (new_status, code),
    )
    if new_status == "funded" and loan_amount:
        conn.execute(
            """UPDATE results SET loan_amount = ?
            WHERE code = ?""",
            (loan_amount, code),
        )
    conn.commit()
    conn.close()

    return jsonify({"success": True, "code": code, "status": new_status})


@app.route("/uploads/<filename>")
def serve_upload(filename):
    return send_from_directory("/tmp", filename)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
