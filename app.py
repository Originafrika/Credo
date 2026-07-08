import base64
import json
import os
import re
import uuid
from datetime import datetime
from decimal import Decimal

from flask import Flask, render_template, request, jsonify, session, send_from_directory
import psycopg2
import psycopg2.extras

from credo_ai import (
    build_first_question,
    build_questionnaire,
    build_questionnaire_blocks,
    build_next_question,
    build_document_requests,
    extract_document_fields,
    generate_code,
    build_comparison_report,
    _get_all_partners,
)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "credo-dev-2026")

@app.after_request
def security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["X-XSS-Protection"] = "1; mode=block"
    resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return resp

class _JsonEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        return super().default(o)
app.json_encoder = _JsonEncoder

NEON_DSN = os.environ.get("NEON_DSN", "")
if not NEON_DSN:
    print("[CREDO] FATAL: NEON_DSN not set", flush=True)
    raise SystemExit(1)

def get_db():
    if not NEON_DSN:
        raise RuntimeError("NEON_DSN not configured")
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

def init_db():
    if not NEON_DSN:
        return
    conn = get_db()
    for sql in [
        "CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, phone TEXT, plan TEXT DEFAULT '5000', status TEXT DEFAULT 'payment_wait', code TEXT, payment_ref TEXT, payment_verified INTEGER DEFAULT 0, created_at TEXT DEFAULT NOW(), completed_at TEXT, questionnaire TEXT, question_idx INTEGER DEFAULT 0)",
        "CREATE TABLE IF NOT EXISTS messages (id SERIAL PRIMARY KEY, session_id TEXT, role TEXT, question TEXT, answer TEXT, created_at TEXT DEFAULT NOW())",
        "CREATE TABLE IF NOT EXISTS documents (id SERIAL PRIMARY KEY, session_id TEXT, doc_type TEXT, storage_url TEXT, extracted_json TEXT, created_at TEXT DEFAULT NOW())",
        "CREATE TABLE IF NOT EXISTS results (id SERIAL PRIMARY KEY, session_id TEXT UNIQUE, score INTEGER, risk TEXT, max_amount INTEGER, partners TEXT, missing_docs TEXT, tips TEXT, code TEXT UNIQUE, loan_amount INTEGER, analysis TEXT, created_at TEXT DEFAULT NOW())",
    ]:
        db_execute(conn, sql)
    try:
        db_execute(conn, "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS questionnaire TEXT")
        db_execute(conn, "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS question_idx INTEGER DEFAULT 0")
        db_execute(conn, "ALTER TABLE results ADD COLUMN IF NOT EXISTS max_amount INTEGER DEFAULT 0")
        db_execute(conn, "ALTER TABLE results ADD COLUMN IF NOT EXISTS missing_docs TEXT")
        db_execute(conn, "ALTER TABLE results ADD COLUMN IF NOT EXISTS tips TEXT")
        db_execute(conn, "ALTER TABLE results ADD COLUMN IF NOT EXISTS analysis TEXT")
        db_execute(conn, "CREATE UNIQUE INDEX IF NOT EXISTS idx_results_session ON results(session_id)")
        print("[CREDO] migration ok", flush=True)
    except Exception as e:
        print(f"[CREDO] migration note: {e}", flush=True)
    conn.close()

init_db()

@app.route("/api/questions")
def get_questions():
    default = [
        "Quelle est ton activité principale ?",
        "Depuis combien de temps exerces-tu ?",
        "Quel est ton revenu mensuel moyen ?",
        "Quel montant souhaites-tu emprunter ?",
        "As-tu déjà eu un crédit ?",
        "As-tu une épargne ?",
        "Quelle est la destination du prêt ?",
        "As-tu des garanties à proposer ?",
        "As-tu un RC ou une patente ?",
    ]
    try:
        partners, products = _get_all_partners()
        if not partners:
            return jsonify({"questions": default})
        sectors = set()
        amounts = []
        has_docs = False
        for p in partners:
            if p.get("sectors"):
                for s in p["sectors"]:
                    sectors.add(s)
            if p.get("min_amount"):
                amounts.append(p["min_amount"])
            if p.get("max_amount"):
                amounts.append(p["max_amount"])
            if p.get("docs"):
                has_docs = True
        min_a = min(amounts) if amounts else 50000
        max_a = max(amounts) if amounts else 5000000
        questions = [
            f"Quelle est ton activité principale ?",
        ]
        if len(sectors) > 1:
            sect_list = ", ".join(sorted(sectors)[:5])
            questions.append(f"Dans quel secteur exerces-tu ? ({sect_list}, ou autre)")
        questions.append("Depuis combien de temps exerces-tu ?")
        questions.append("Quel est ton revenu mensuel moyen ?")
        questions.append(f"Quel montant souhaites-tu emprunter ? (fourchette disponible : {min_a:,} - {max_a:,} FCFA)")
        questions.append("As-tu déjà eu un crédit ?")
        questions.append("As-tu une épargne ?")
        questions.append("Quelle est la destination du prêt ?")
        questions.append("As-tu des garanties à proposer ?")
        if has_docs:
            questions.append("Peux-tu fournir des documents (pièce d'identité, justificatif de revenus, etc.) ?")
        return jsonify({"questions": questions})
    except Exception as e:
        return jsonify({"questions": default})

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/chat/new")
def new_chat():
    return render_template("chat.html")

@app.route("/chat/<session_id>")
def chat_session(session_id):
    return render_template("chat.html", session_id=session_id)

@app.route("/api/chat/<session_id>/resume")
def resume_session(session_id):
    try:
        conn = get_db()
    except Exception as e:
        print(f"[CREDO] DB connection error: {e}", flush=True)
        return jsonify({"error": "Service indisponible"}), 503
    try:
        s = db_fetchone(conn, "SELECT * FROM sessions WHERE id = %s", (session_id,))
        if not s:
            db_close(conn)
            return jsonify({"error": "Session invalide"}), 404
        last = db_fetchone(conn, "SELECT question FROM messages WHERE session_id = %s AND role = 'ia' ORDER BY id DESC LIMIT 1", (session_id,))
        count = db_fetchone(conn, "SELECT COUNT(*) AS c FROM messages WHERE session_id = %s AND role = 'user'", (session_id,))
        db_close(conn)
        return jsonify({
            "question": last["question"] if last else build_first_question(),
            "done": False,
        })
    except Exception as e:
        db_close(conn)
        print(f"[CREDO] DB error in resume_session: {e}", flush=True)
        return jsonify({"error": "Erreur lors de la récupération"}), 500

@app.route("/api/session/start", methods=["POST"])
def start_session():
    data = request.json
    phone = data.get("phone", "").strip()
    plan = data.get("plan", "2500")
    if not phone:
        return jsonify({"error": "Numero de telephone requis"}), 400
    cleaned = re.sub(r'[\s\+\-\(\)]', '', phone)
    if not re.match(r'^\d{8,15}$', cleaned):
        return jsonify({"error": "Numero de telephone invalide (8-15 chiffres)"}), 400
    if plan not in ("2500", "5000"):
        plan = "2500"
    session_id = uuid.uuid4().hex[:8]
    try:
        conn = get_db()
    except Exception as e:
        print(f"[CREDO] DB connection error: {e}", flush=True)
        return jsonify({"error": "Service indisponible"}), 503
    try:
        db_execute(conn, "INSERT INTO sessions (id, phone, plan) VALUES (%s, %s, %s)", (session_id, cleaned, plan))
        first_q = build_first_question()
        db_execute(conn, "INSERT INTO messages (session_id, role, question) VALUES (%s, 'ia', %s)", (session_id, first_q))
        db_close(conn)
        return jsonify({"session_id": session_id, "first_question": first_q})
    except Exception as e:
        db_close(conn)
        print(f"[CREDO] DB error in start_session: {e}", flush=True)
        return jsonify({"error": "Erreur lors de la création"}), 500

@app.route("/api/chat/<session_id>/message", methods=["POST"])
def chat_message(session_id):
    data = request.json
    answer = data.get("answer", "").strip()
    if not answer:
        return jsonify({"error": "Reponse vide"}), 400
    try:
        conn = get_db()
    except Exception as e:
        print(f"[CREDO] DB connection error: {e}", flush=True)
        return jsonify({"error": "Service indisponible"}), 503
    try:
        s = db_fetchone(conn, "SELECT * FROM sessions WHERE id = %s", (session_id,))
        if not s:
            db_close(conn)
            return jsonify({"error": "Session invalide"}), 404
        last = db_fetchone(conn, "SELECT question FROM messages WHERE session_id = %s AND role = 'ia' ORDER BY id DESC LIMIT 1", (session_id,))
        last_q = last["question"] if last else "Question"
        db_execute(conn, "INSERT INTO messages (session_id, role, question, answer) VALUES (%s, 'user', %s, %s)", (session_id, last_q, answer))
        user_count = db_fetchone(conn, "SELECT COUNT(*) AS c FROM messages WHERE session_id = %s AND role = 'user'", (session_id,))
    except Exception as e:
        db_close(conn)
        print(f"[CREDO] DB error in chat_message: {e}", flush=True)
        return jsonify({"error": "Erreur lors de l'enregistrement"}), 500

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

    try:
        msgs = db_execute(conn, "SELECT question, answer FROM messages WHERE session_id = %s AND role = 'user' ORDER BY id", (session_id,))
    except Exception as e:
        db_close(conn)
        print(f"[CREDO] DB error fetching messages: {e}", flush=True)
        return jsonify({"error": "Erreur lors de la récupération"}), 500
    answers = [{"q": m["question"], "a": m["answer"]} for m in msgs]
    try:
        next_q = build_next_question(answers)
    except Exception:
        db_close(conn)
        return jsonify({"error": "Credo IA indisponible."}), 503
    try:
        db_execute(conn, "INSERT INTO messages (session_id, role, question) VALUES (%s, 'ia', %s)", (session_id, next_q))
    except Exception as e:
        db_close(conn)
        print(f"[CREDO] DB error inserting next question: {e}", flush=True)
        return jsonify({"error": "Erreur lors de l'enregistrement"}), 500
    db_close(conn)
    if next_q == "DONE":
        return jsonify({"done": True})
    return jsonify({"question": next_q, "done": False})

@app.route("/api/chat/<session_id>/questionnaire-answers", methods=["POST"])
def submit_questionnaire(session_id):
    data = request.json
    answers_list = data.get("answers", [])
    questions_list = data.get("questions", [])
    if not answers_list or not isinstance(answers_list, list):
        return jsonify({"error": "Reponses invalides"}), 400
    try:
        conn = get_db()
    except Exception as e:
        print(f"[CREDO] DB connection error: {e}", flush=True)
        return jsonify({"error": "Service indisponible"}), 503
    try:
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
    except Exception as e:
        db_close(conn)
        print(f"[CREDO] DB error in submit_questionnaire: {e}", flush=True)
        return jsonify({"error": "Erreur lors de l'enregistrement"}), 500

@app.route("/api/chat/<session_id>/document-requests", methods=["POST"])
def document_requests(session_id):
    try:
        conn = get_db()
        msgs = db_execute(conn, "SELECT question, answer FROM messages WHERE session_id = %s AND role = 'user' ORDER BY id", (session_id,))
        db_close(conn)
        if not msgs:
            return jsonify({"requests": []})
        answers = [{"q": m["question"], "a": m["answer"]} for m in msgs]
        requests = build_document_requests(answers)
        if requests:
            return jsonify({"requests": requests})
        return jsonify({"requests": []})
    except Exception as e:
        print(f"[CREDO] document_requests error: {e}", flush=True)
        return jsonify({"requests": []})

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

        docs = db_execute(conn, "SELECT id, doc_type, storage_url, extracted_json FROM documents WHERE session_id = %s", (session_id,))
        document_extractions = []
        for d in docs:
            if d.get("extracted_json"):
                try:
                    document_extractions.append(json.loads(d["extracted_json"]))
                except (json.JSONDecodeError, TypeError):
                    pass
                continue
            fpath = os.path.join("uploads", d["storage_url"])
            if os.path.isfile(fpath):
                try:
                    with open(fpath, "rb") as f:
                        b64 = base64.b64encode(f.read()).decode("utf-8")
                    ext = os.path.splitext(d["storage_url"])[1].lower()
                    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif", "webp": "image/webp"}.get(ext.lstrip("."), "image/jpeg")
                    data_url = f"data:{mime};base64,{b64}"
                    extracted = extract_document_fields(data_url, d.get("doc_type", "unknown"))
                    if extracted and "error" not in extracted:
                        document_extractions.append(extracted)
                        conn2 = get_db()
                        db_execute(conn2, "UPDATE documents SET extracted_json = %s WHERE id = %s", (json.dumps(extracted), d["id"]))
                        conn2.close()
                except Exception as e:
                    print(f"[CREDO] vision extract failed for {d['storage_url']}: {e}", flush=True)
            else:
                print(f"[CREDO] file not found for vision: {d['storage_url']}", flush=True)

        report = build_comparison_report(answers, document_extractions)
        code = None
        plan = s["plan"]
        if plan == "5000":
            code = generate_code()
        db_execute(conn,
            "INSERT INTO results (session_id, score, risk, max_amount, partners, missing_docs, tips, code, analysis) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (session_id) DO UPDATE SET score=excluded.score, risk=excluded.risk, max_amount=excluded.max_amount, partners=excluded.partners, missing_docs=excluded.missing_docs, tips=excluded.tips, code=excluded.code, analysis=excluded.analysis",
            (session_id, report["score"], report.get("risk", "N/A"), report.get("max_amount", 0), json.dumps(report.get("top_recommendations", []) if plan == "5000" else report.get("top_recommendations", [])[:1]), json.dumps(report.get("missing_documents", []) if plan == "5000" else []), json.dumps(report.get("improvement_tips", []) if plan == "5000" else []), code, report.get("analysis", "") if plan == "5000" else "")
        )
        db_execute(conn, "UPDATE sessions SET status = 'completed', code = %s, completed_at = NOW() WHERE id = %s", (code, session_id))
        db_close(conn)
        resp = {
            "score": report["score"],
            "risk": report.get("risk", "N/A"),
            "plan": plan,
            "max_amount": report.get("max_amount", 0),
        }
        if plan == "5000":
            resp.update({
                "analysis": report.get("analysis", ""),
                "partners": report.get("top_recommendations", []),
                "missing_documents": report.get("missing_documents", []),
                "tips": report.get("improvement_tips", []),
                "code": code,
                "profil": report.get("profil", {}),
                "layer2": report.get("layer2", {}),
            })
        return jsonify(resp)
    except Exception as e:
        print(f"[CREDO] analyze error: {e}", flush=True)
        return jsonify({"error": f"Erreur: {str(e)[:300]}"}), 500

@app.route("/api/chat/<session_id>/result")
def get_result(session_id):
    try:
        conn = get_db()
    except Exception as e:
        print(f"[CREDO] DB connection error: {e}", flush=True)
        return jsonify({"error": "Service indisponible"}), 503
    try:
        result = db_fetchone(conn, "SELECT * FROM results WHERE session_id = %s", (session_id,))
        s = db_fetchone(conn, "SELECT * FROM sessions WHERE id = %s", (session_id,))
        db_close(conn)
        if not result:
            return jsonify({"error": "Analyse non trouvee"}), 404
        plan = s["plan"] if s else "2500"
        is_simple = plan == "2500"
        return jsonify({
            "score": result["score"],
            "risk": result["risk"],
            "max_amount": result["max_amount"],
            "partners": json.loads(result["partners"]) if not is_simple else [],
            "missing_documents": json.loads(result["missing_docs"]) if not is_simple else [],
            "tips": json.loads(result["tips"]) if not is_simple else [],
            "code": result["code"],
            "analysis": result["analysis"] if not is_simple else "",
            "plan": plan,
        })
    except Exception as e:
        db_close(conn)
        print(f"[CREDO] DB error in get_result: {e}", flush=True)
        return jsonify({"error": "Erreur lors de la récupération"}), 500

@app.route("/api/chat/<session_id>/report")
def api_report(session_id):
    try:
        conn = get_db()
    except Exception as e:
        print(f"[CREDO] DB connection error: {e}", flush=True)
        return jsonify({"error": "Service indisponible"}), 503
    try:
        s = db_fetchone(conn, "SELECT * FROM sessions WHERE id = %s", (session_id,))
        if not s:
            db_close(conn)
            return jsonify({"error": "Session invalide"}), 404
        msgs = db_execute(conn, "SELECT question, answer FROM messages WHERE session_id = %s AND role = 'user' ORDER BY id", (session_id,))
        docs = db_execute(conn, "SELECT doc_type, storage_url, extracted_json FROM documents WHERE session_id = %s", (session_id,))
        db_close(conn)
        answers = [{"q": m["question"], "a": m["answer"]} for m in msgs]
        document_extractions = []
        for d in docs:
            if d.get("extracted_json"):
                try:
                    document_extractions.append(json.loads(d["extracted_json"]))
                except (json.JSONDecodeError, TypeError):
                    pass
        try:
            report = build_comparison_report(answers, document_extractions)
        except Exception as e:
            return jsonify({"error": f"Erreur: {str(e)[:200]}"}), 503
        return jsonify(report)
    except Exception as e:
        db_close(conn)
        print(f"[CREDO] DB error in api_report: {e}", flush=True)
        return jsonify({"error": "Erreur lors de la récupération"}), 500

@app.route("/report/<session_id>")
def view_report(session_id):
    try:
        conn = get_db()
    except Exception as e:
        print(f"[CREDO] DB connection error: {e}", flush=True)
        return render_template("error.html", message="Service indisponible")
    try:
        s = db_fetchone(conn, "SELECT * FROM sessions WHERE id = %s", (session_id,))
        if not s:
            db_close(conn)
            return render_template("error.html", message="Session invalide")
        plan = s.get("plan", "2500")
        msgs = db_execute(conn, "SELECT question, answer FROM messages WHERE session_id = %s AND role = 'user' ORDER BY id", (session_id,))
        docs = db_execute(conn, "SELECT doc_type, storage_url, extracted_json FROM documents WHERE session_id = %s", (session_id,))
        db_close(conn)
        answers = [{"q": m["question"], "a": m["answer"]} for m in msgs]
        document_extractions = []
        for d in docs:
            if d.get("extracted_json"):
                try:
                    document_extractions.append(json.loads(d["extracted_json"]))
                except (json.JSONDecodeError, TypeError):
                    pass
        try:
            report = build_comparison_report(answers, document_extractions)
        except Exception as e:
            return render_template("error.html", message=f"Erreur rapport: {e}")
        l2 = report.get("layer2", {})
        is_simple = plan == "2500"
        return render_template("report.html",
            total=report.get("total_institutions", 0),
            eligible=report.get("eligible_count", 0),
            partial=report.get("partial_count", 0),
            not_eligible=report.get("not_eligible_count", 0),
            score=report.get("score", 0),
            risk=report.get("risk", "N/A"),
            max_amount=report.get("max_amount", 0),
            realistic_max=report.get("profil", {}).get("realistic_max", 0),
            sector=report.get("profil", {}).get("sector", "N/A"),
            monthly_income=report.get("profil", {}).get("monthly_income", 0),
            amount_wanted=report.get("profil", {}).get("amount_wanted", 0),
            collateral="Oui" if report.get("profil", {}).get("collateral") else "Non",
            business_reg="Oui" if report.get("profil", {}).get("business_registration") else "Non",
            recommendations=report.get("top_recommendations", []) if not is_simple else report.get("top_recommendations", [])[:1],
            all_comparisons=report.get("all_comparisons", []) if not is_simple else [],
            analysis=report.get("analysis", "") if not is_simple else "Rapport Simple — passe au Rapport Complet (5,000 FCFA) pour l'analyse detaillee et la comparaison complete.",
            missing_documents=report.get("missing_documents", []) if not is_simple else [],
            improvement_tips=report.get("improvement_tips", []) if not is_simple else [],
            layer2_summary=l2.get("summary", "") if not is_simple else "",
            layer2_best_match=l2.get("best_match", "") if not is_simple else "",
            layer2_best_reason=l2.get("best_reason", "") if not is_simple else "",
            layer2_recs=l2.get("recommendations", [])[:3] if not is_simple else [],
            is_simple=is_simple,
        )
    except Exception as e:
        db_close(conn)
        print(f"[CREDO] DB error in view_report: {e}", flush=True)
        return render_template("error.html", message="Erreur lors du chargement du rapport")

@app.route("/api/documents/upload/<session_id>", methods=["POST"])
def upload_document(session_id):
    try:
        if "file" not in request.files:
            return jsonify({"error": "Aucun fichier"}), 400
        file = request.files["file"]
        if file.filename == "":
            return jsonify({"error": "Fichier vide"}), 400
        doc_type = request.form.get("doc_type", "unknown")
        ext = os.path.splitext(file.filename)[1] or ".bin"
        file_name = f"doc_{session_id}_{doc_type}_{uuid.uuid4().hex[:8]}{ext}"
        os.makedirs("uploads", exist_ok=True)
        file.save(os.path.join("uploads", file_name))
        conn = get_db()
        db_execute(conn, "INSERT INTO documents (session_id, doc_type, storage_url) VALUES (%s, %s, %s)", (session_id, doc_type, file_name))
        db_close(conn)
        return jsonify({"status": "ok", "filename": file_name})
    except Exception as e:
        print(f"[CREDO] upload error: {e}", flush=True)
        return jsonify({"error": "Erreur lors de l'upload"}), 500

@app.route("/verify/<code>")
def verify_code(code):
    try:
        conn = get_db()
    except Exception as e:
        print(f"[CREDO] DB connection error: {e}", flush=True)
        return render_template("error.html", message="Service indisponible")
    try:
        result = db_fetchone(conn,
            "SELECT r.score, r.max_amount, r.risk, r.code, r.partners, r.missing_docs, r.tips, r.created_at, s.phone, s.status as session_status FROM results r JOIN sessions s ON r.session_id = s.id WHERE r.code = %s", (code,))
        db_close(conn)
        if not result:
            return render_template("verify.html", code=code, valid=False)
        try:
            partners_list = json.loads(result["partners"]) if result["partners"] else []
            missing_docs = json.loads(result["missing_docs"]) if result["missing_docs"] else []
            tips = json.loads(result["tips"]) if result["tips"] else []
        except (json.JSONDecodeError, TypeError):
            partners_list = []
            missing_docs = []
            tips = []
        return render_template("verify.html", code=code, valid=True,
            score=result["score"], max_amount=result["max_amount"],
            risk=result["risk"], partners=partners_list,
            missing_documents=missing_docs, tips=tips,
            created_at=result["created_at"], phone=result["phone"],
            session_status=result["session_status"])
    except Exception as e:
        db_close(conn)
        print(f"[CREDO] DB error in verify_code: {e}", flush=True)
        return render_template("error.html", message="Erreur lors de la vérification")

@app.route("/api/verify/<code>/update", methods=["POST"])
def update_verify(code):
    data = request.json
    try:
        conn = get_db()
    except Exception as e:
        print(f"[CREDO] DB connection error: {e}", flush=True)
        return jsonify({"error": "Service indisponible"}), 503
    try:
        r = db_fetchone(conn, "SELECT session_id FROM results WHERE code = %s", (code,))
        if not r:
            db_close(conn)
            return jsonify({"error": "Code invalide"}), 404
        db_execute(conn, "UPDATE sessions SET status = %s, payment_ref = %s, payment_verified = 1 WHERE id = %s",
            (data.get("status", "completed"), data.get("payment_ref", ""), r["session_id"]))
        db_close(conn)
        return jsonify({"ok": True})
    except Exception as e:
        db_close(conn)
        print(f"[CREDO] DB error in update_verify: {e}", flush=True)
        return jsonify({"error": "Erreur lors de la mise à jour"}), 500

@app.route("/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory("uploads", filename)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
