import json
import os
import uuid
from datetime import datetime

from flask import Flask, render_template, request, jsonify, session, send_from_directory
import psycopg2
import psycopg2.extras

from credo_ai import (
    build_first_question,
    build_questionnaire,
    build_questionnaire_blocks,
    build_next_question,
    extract_document_fields,
    generate_code,
    build_comparison_report,
)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "credo-dev-2026")
from decimal import Decimal
class _JsonEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        return super().default(o)
app.json_encoder = _JsonEncoder

NEON_DSN = os.environ.get("NEON_DSN", "")
if not NEON_DSN:
    raise RuntimeError("NEON_DSN environment variable is required")

# ── DB layer ──

def get_db():
    return psycopg2.connect(NEON_DSN)

def db_execute(conn, sql, params=None):
    is_select = sql.strip().upper().startswith("SELECT")
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params or ())
        if is_select:
            return cur.fetchall()
        conn.commit()
        return None

def db_fetchone(conn, sql, params=None):
    rows = db_execute(conn, sql, params)
    return rows[0] if rows else None

def db_close(conn):
    try:
        conn.close()
    except:
        pass

# ── Init DB ──

def init_db():
    conn = get_db()
    for sql in [
        "CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, phone TEXT, plan TEXT DEFAULT '5000', status TEXT DEFAULT 'payment_wait', code TEXT, payment_ref TEXT, payment_verified INTEGER DEFAULT 0, created_at TEXT DEFAULT NOW(), completed_at TEXT, questionnaire TEXT, question_idx INTEGER DEFAULT 0)",
        "CREATE TABLE IF NOT EXISTS messages (id SERIAL PRIMARY KEY, session_id TEXT, role TEXT, question TEXT, answer TEXT, created_at TEXT DEFAULT NOW())",
        "CREATE TABLE IF NOT EXISTS documents (id SERIAL PRIMARY KEY, session_id TEXT, doc_type TEXT, storage_url TEXT, extracted_json TEXT, created_at TEXT DEFAULT NOW())",
        "CREATE TABLE IF NOT EXISTS results (id SERIAL PRIMARY KEY, session_id TEXT UNIQUE, score INTEGER, risk TEXT, max_amount INTEGER, partners TEXT, missing_docs TEXT, tips TEXT, code TEXT UNIQUE, loan_amount INTEGER, analysis TEXT, created_at TEXT DEFAULT NOW())",
    ]:
        try:
            db_execute(conn, sql)
        except Exception:
            pass
    try:
        db_execute(conn, "DELETE FROM results WHERE score > 600")
        db_execute(conn, "DELETE FROM sessions WHERE status = 'completed'")
    except Exception:
        pass
    db_close(conn)

init_db()

_migrated = False

@app.before_request
def ensure_migration():
    global _migrated
    if _migrated:
        return
    try:
        conn = get_db()
        db_execute(conn, "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS questionnaire TEXT")
        db_execute(conn, "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS question_idx INTEGER DEFAULT 0")
        db_execute(conn, "ALTER TABLE results ADD COLUMN IF NOT EXISTS max_amount INTEGER DEFAULT 0")
        db_execute(conn, "ALTER TABLE results ADD COLUMN IF NOT EXISTS missing_docs TEXT")
        db_execute(conn, "ALTER TABLE results ADD COLUMN IF NOT EXISTS tips TEXT")
        db_execute(conn, "ALTER TABLE results ADD COLUMN IF NOT EXISTS analysis TEXT")
        db_close(conn)
        _migrated = True
        print("[CREDO] migration ok", flush=True)
    except Exception as e:
        print(f"[CREDO] migration failed: {e}", flush=True)

# ── Routes ──

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/chat/new")
def chat_new():
    return render_template("chat_new.html")

@app.route("/chat/<session_id>")
def chat(session_id):
    conn = get_db()
    s = db_fetchone(conn, "SELECT * FROM sessions WHERE id = %s", (session_id,))
    db_close(conn)
    if not s:
        return render_template("chat_new.html")
    return render_template("chat.html", session_id=session_id, plan=s["plan"])

@app.route("/api/session/start", methods=["POST"])
def start_session():
    data = request.json
    phone = data.get("phone", "").strip()
    plan = data.get("plan", "5000")
    if not phone or len(phone) < 6:
        return jsonify({"error": "Numero invalide"}), 400
    session_id = str(uuid.uuid4())[:8]
    conn = get_db()
    db_execute(conn, "INSERT INTO sessions (id, phone, plan, status) VALUES (%s, %s, %s, 'chat_active')", (session_id, phone, plan))
    try:
        first_q = build_first_question()
    except Exception:
        db_close(conn)
        return jsonify({"error": "Credo IA indisponible. Capture d'ecran avec ta requete a it@originafrika.online"}), 503
    db_execute(conn, "INSERT INTO messages (session_id, role, question) VALUES (%s, 'ia', %s)", (session_id, first_q))
    db_close(conn)
    return jsonify({"session_id": session_id, "first_question": first_q})

@app.route("/api/chat/<session_id>/message", methods=["POST"])
def chat_message(session_id):
    data = request.json
    answer = data.get("answer", "").strip()
    if not answer:
        return jsonify({"error": "Reponse vide"}), 400
    conn = get_db()
    s = db_fetchone(conn, "SELECT * FROM sessions WHERE id = %s", (session_id,))
    if not s:
        db_close(conn)
        return jsonify({"error": "Session invalide"}), 404

    last = db_fetchone(conn, "SELECT question FROM messages WHERE session_id = %s AND role = 'ia' ORDER BY id DESC LIMIT 1", (session_id,))
    last_q = last["question"] if last else "Question"
    db_execute(conn, "INSERT INTO messages (session_id, role, question, answer) VALUES (%s, 'user', %s, %s)", (session_id, last_q, answer))

    user_count = db_fetchone(conn, "SELECT COUNT(*) AS c FROM messages WHERE session_id = %s AND role = 'user'", (session_id,))

    # First answer → generate questionnaire with LLM-decided blocks, return for progressive blocks
    if user_count and user_count["c"] == 1:
        try:
            result = build_questionnaire_blocks(answer)
            blocks = result["blocks"]
            questions = [q for block in blocks for q in block]
            if questions:
                db_execute(conn, "UPDATE sessions SET questionnaire = %s, question_idx = 0 WHERE id = %s", (json.dumps(questions), session_id))
                db_close(conn)
                return jsonify({"type": "questionnaire", "blocks": blocks, "questions": questions, "done": False})
            db_close(conn)
            return jsonify({"done": True})
        except Exception as e:
            print(f"[CREDO] chat_message questionnaire error: {e}", flush=True)
            db_close(conn)
            return jsonify({"error": f"Erreur: {str(e)[:200]}"}), 503

    # Normal single-question flow (after questionnaire or standalone)
    msgs = db_execute(conn, "SELECT question, answer FROM messages WHERE session_id = %s AND role = 'user' ORDER BY id", (session_id,))
    answers = [{"q": m["question"], "a": m["answer"]} for m in msgs]
    try:
        next_q = build_next_question(answers)
    except Exception:
        db_close(conn)
        return jsonify({"error": "Credo IA indisponible."}), 503
    db_execute(conn, "INSERT INTO messages (session_id, role, question) VALUES (%s, 'ia', %s)", (session_id, next_q))
    db_close(conn)
    if next_q == "DONE":
        return jsonify({"done": True})
    return jsonify({"question": next_q, "done": False})

@app.route("/api/chat/<session_id>/questionnaire-answers", methods=["POST"])
def submit_questionnaire(session_id):
    """Reçoit toutes les reponses du formulaire progressif en une seule requete."""
    data = request.json
    answers_list = data.get("answers", [])
    questions_list = data.get("questions", [])
    if not answers_list or not isinstance(answers_list, list):
        return jsonify({"error": "Reponses invalides"}), 400
    conn = get_db()
    s = db_fetchone(conn, "SELECT * FROM sessions WHERE id = %s", (session_id,))
    if not s:
        db_close(conn)
        return jsonify({"error": "Session invalide"}), 404
    for i, ans in enumerate(answers_list):
        if not ans or not ans.strip():
            continue
        q_text = questions_list[i] if i < len(questions_list) else "Question {}".format(i + 1)
        db_execute(conn, "INSERT INTO messages (session_id, role, question, answer) VALUES (%s, 'user', %s, %s)", (session_id, q_text, ans.strip()))
    db_execute(conn, "UPDATE sessions SET questionnaire = NULL, question_idx = 0 WHERE id = %s", (session_id,))
    db_close(conn)
    return jsonify({"done": True, "accepted": len([a for a in answers_list if a and a.strip()])})

@app.route("/api/chat/<session_id>/analyze", methods=["POST"])
def analyze(session_id):
    try:
        conn = get_db()
        s = db_fetchone(conn, "SELECT * FROM sessions WHERE id = %s", (session_id,))
        if not s:
            db_close(conn)
            return jsonify({"error": "Session invalide"}), 404
        msgs = db_execute(conn, "SELECT question, answer FROM messages WHERE session_id = %s AND role = 'user' ORDER BY id", (session_id,))
        if not msgs:
            db_close(conn)
            return jsonify({"error": "Aucune reponse"}), 400
        answers = [{"q": m["question"], "a": m["answer"]} for m in msgs]
        report = build_comparison_report(answers)
        code = None
        plan = s["plan"]
        if plan == "5000":
            code = generate_code()
        db_execute(conn,
            "INSERT INTO results (session_id, score, risk, max_amount, partners, missing_docs, tips, code, analysis) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (session_id, report["score"], report.get("risk", "N/A"), report.get("max_amount", 0), json.dumps(report.get("top_recommendations", [])), json.dumps(report.get("missing_documents", [])), json.dumps(report.get("improvement_tips", [])), code, report.get("analysis", ""))
        )
        db_execute(conn, "UPDATE sessions SET status = 'completed', code = %s, completed_at = NOW() WHERE id = %s", (code, session_id))
        db_close(conn)
        return jsonify({
            "score": report["score"],
            "risk": report.get("risk", "N/A"),
            "analysis": report.get("analysis", ""),
            "partners": report.get("top_recommendations", []),
            "missing_documents": report.get("missing_documents", []),
            "tips": report.get("improvement_tips", []),
            "code": code,
            "plan": plan,
        })
    except Exception as e:
        print(f"[CREDO] analyze error: {e}", flush=True)
        return jsonify({"error": f"Erreur: {str(e)[:300]}"}), 500

@app.route("/api/chat/<session_id>/result")
def get_result(session_id):
    conn = get_db()
    result = db_fetchone(conn, "SELECT * FROM results WHERE session_id = %s", (session_id,))
    s = db_fetchone(conn, "SELECT * FROM sessions WHERE id = %s", (session_id,))
    db_close(conn)
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
        "plan": s["plan"] if s else "2500",
    })

@app.route("/api/chat/<session_id>/report")
def api_report(session_id):
    conn = get_db()
    s = db_fetchone(conn, "SELECT * FROM sessions WHERE id = %s", (session_id,))
    if not s:
        db_close(conn)
        return jsonify({"error": "Session invalide"}), 404
    msgs = db_execute(conn, "SELECT question, answer FROM messages WHERE session_id = %s AND role = 'user' ORDER BY id", (session_id,))
    db_close(conn)
    answers = [{"q": m["question"], "a": m["answer"]} for m in msgs]
    try:
        report = build_comparison_report(answers)
    except Exception as e:
        return jsonify({"error": f"Erreur: {str(e)[:200]}"}), 503
    return jsonify(report)


@app.route("/report/<session_id>")
def view_report(session_id):
    conn = get_db()
    s = db_fetchone(conn, "SELECT * FROM sessions WHERE id = %s", (session_id,))
    if not s:
        db_close(conn)
        return render_template("error.html", message="Session invalide")
    msgs = db_execute(conn, "SELECT question, answer FROM messages WHERE session_id = %s AND role = 'user' ORDER BY id", (session_id,))
    db_close(conn)
    answers = [{"q": m["question"], "a": m["answer"]} for m in msgs]
    try:
        report = build_comparison_report(answers)
    except Exception as e:
        return render_template("error.html", message=f"Erreur: {str(e)[:200]}")
    return render_template("report.html", report=report)




@app.route("/api/documents/upload/<session_id>", methods=["POST"])
def upload_document(session_id):
    if "file" not in request.files:
        return jsonify({"error": "Aucun fichier"}), 400
    file = request.files["file"]
    doc_type = request.form.get("doc_type", "other")
    if file.filename == "":
        return jsonify({"error": "Fichier vide"}), 400
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else "jpg"
    doc_id = str(uuid.uuid4())[:8]
    filename = f"{session_id}_{doc_id}.{ext}"
    filepath = os.path.join("/tmp", filename)
    file.save(filepath)
    storage_url = f"/uploads/{filename}"
    conn = get_db()
    db_execute(conn, "INSERT INTO documents (session_id, doc_type, storage_url) VALUES (%s, %s, %s)", (session_id, doc_type, storage_url))
    db_close(conn)
    return jsonify({"document_id": doc_id, "storage_url": storage_url})

@app.route("/api/debug/report/<session_id>")
def debug_report(session_id):
    try:
        conn = get_db()
        msgs = db_execute(conn, "SELECT question, answer FROM messages WHERE session_id = %s AND role = 'user' ORDER BY id", (session_id,))
        db_close(conn)
        if not msgs:
            return jsonify({"error": "no messages", "session": session_id})
        answers = [{"q": m["question"], "a": m["answer"]} for m in msgs]
        report = build_comparison_report(answers)
        return jsonify({"ok": True, "score": report.get("score"), "risk": report.get("risk"), "partners_count": len(report.get("top_recommendations", []))})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:500], "type": type(e).__name__}), 500

@app.route("/verify/<code>")
def verify_code(code):
    conn = get_db()
    result = db_fetchone(conn,
        "SELECT r.score, r.max_amount, r.risk, r.code, r.partners, r.missing_docs, r.tips, r.created_at, s.phone, s.status as session_status FROM results r JOIN sessions s ON r.session_id = s.id WHERE r.code = %s", (code,))
    db_close(conn)
    if not result:
        return render_template("verify.html", code=code, valid=False)
    partners_data = json.loads(result["partners"]) if result["partners"] else []
    missing_docs = json.loads(result["missing_docs"]) if result["missing_docs"] else []
    tips_data = json.loads(result["tips"]) if result["tips"] else []
    return render_template("verify.html",
        code=code, valid=True,
        score=result["score"], max_amount=result["max_amount"], risk=result["risk"],
        partners=partners_data, missing_docs=missing_docs, tips=tips_data,
        phone=result["phone"][:3] + "XX" + result["phone"][-2:],
        created_at=result["created_at"])

@app.route("/api/verify/<code>/update", methods=["POST"])
def update_referral(code):
    data = request.json
    new_status = data.get("status")
    loan_amount = data.get("loan_amount")
    if new_status not in ["contacted", "approved", "funded", "rejected"]:
        return jsonify({"error": "Statut invalide"}), 400
    conn = get_db()
    db_execute(conn, "UPDATE sessions SET status = %s, completed_at = NOW() WHERE code = %s", (new_status, code))
    if new_status == "funded" and loan_amount:
        db_execute(conn, "UPDATE results SET loan_amount = %s WHERE code = %s", (loan_amount, code))
    db_close(conn)
    return jsonify({"success": True, "code": code, "status": new_status})

@app.route("/uploads/<filename>")
def serve_upload(filename):
    return send_from_directory("/tmp", filename)

if __name__ == "__main__":
    app.run(debug=True, port=5000)
