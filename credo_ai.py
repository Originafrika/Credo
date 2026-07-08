import json
import os
import re
import secrets
import string
from datetime import datetime

from groq import Groq
import psycopg2

client = Groq(api_key=os.environ.get("GROQ_API_KEY", ""))

SCORE_MODEL = "llama-3.3-70b-versatile"
VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

NEON_DSN = os.environ.get("NEON_DSN", "")

# ==============================================================
# NEON DB — query real partner data at scoring time
# ==============================================================

def _get_partners(amount: int, sector_hint: str = "", country: str = "TG") -> tuple[list[dict], list[dict], list[dict]]:
    if not NEON_DSN:
        return [], [], []
    try:
        conn = psycopg2.connect(NEON_DSN)
        cur = conn.cursor()

        sectors = ['commerce', 'agriculture', 'service', 'artisanat']
        if sector_hint:
            for s in sectors:
                if s in sector_hint.lower():
                    sectors = [s]
                    break
        cur.execute(
            """SELECT name, type, min_amount, max_amount, rate, sectors, docs, description, base_rate, max_rate, id
               FROM partners
               WHERE countries @> ARRAY[%s]::TEXT[]
                 AND min_amount <= %s
                 AND max_amount >= %s
               ORDER BY
                 CASE WHEN %s BETWEEN min_amount AND max_amount THEN 0 ELSE 1 END,
                 base_rate NULLS LAST,
                 min_amount ASC
               LIMIT 12""",
            (country, amount, amount, amount)
        )
        partners = []
        partner_ids = []
        for r in cur.fetchall():
            partners.append({
                "name": r[0], "type": r[1], "min_amount": r[2], "max_amount": r[3],
                "rate": r[4], "sectors": r[5], "docs": r[6], "description": r[7],
                "base_rate": r[8], "max_rate": r[9],
            })
            partner_ids.append(r[10])

        products = []
        if partner_ids:
            cur.execute(
                """SELECT p.name AS partner_name, pr.name, pr.min_amount, pr.max_amount,
                          pr.min_duration_months, pr.max_duration_months, pr.annual_rate,
                          pr.collateral_required, pr.requirements, pr.description
                   FROM products pr JOIN partners p ON p.id = pr.partner_id
                   WHERE pr.partner_id = ANY(%s)
                     AND pr.max_amount >= %s
                   ORDER BY pr.annual_rate ASC""",
                (partner_ids, amount)
            )
            for r in cur.fetchall():
                products.append({
                    "partner": r[0], "product": r[1], "min_amount": r[2], "max_amount": r[3],
                    "min_duration": r[4], "max_duration": r[5], "annual_rate": r[6],
                    "collateral_required": r[7], "requirements": r[8], "description": r[9],
                })

        cur.execute(
            """SELECT category, title, content FROM knowledge_base ORDER BY category LIMIT 20"""
        )
        rules = [{"category": r[0], "title": r[1], "content": r[2]} for r in cur.fetchall()]

        conn.close()
        return partners, products, rules

    except Exception as e:
        _log(f"Neon query failed: {e}")
        return [], [], []

# ==============================================================
# HELPERS
# ==============================================================

def _log(m: str):
    print(f"[CREDO] {m}")

def generate_code() -> str:
    return "CREDO-" + "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(5))


def _extract_numbers(text: str) -> list[int]:
    text = text.replace(".", "").replace(" ", "").replace(",", ".")
    return [int(float(x)) for x in re.findall(r"\d+(?:\.\d+)?", text)]


def _estimate_monthly_revenue(answers: list[dict]) -> int:
    for a in answers:
        q = (a.get("q") or "").lower()
        r = (a.get("a") or "").lower()
        if "gagnes" in q or "revenu" in q:
            nums = _extract_numbers(r)
            if nums:
                return nums[0]
        if "gagne" in r or "salaire" in r:
            nums = _extract_numbers(r)
            if nums:
                return nums[0]
        if "revenu" in r:
            # Only extract numbers from the sentence containing "revenu"
            for sentence in r.replace("?", ".").replace("!", ".").split("."):
                if "revenu" in sentence:
                    # Check for negation
                    if any(w in sentence for w in ["aucun", "pas de", "sans", "zero", "0"]):
                        return 0
                    nums = _extract_numbers(sentence)
                    if nums:
                        return nums[0]
                    return 0
    return 0


def _extract_amount_wanted(description: str, answers: list[dict]) -> int:
    nums = _extract_numbers(description)
    if nums:
        return max(nums)
    for a in answers:
        q = (a.get("q") or "").lower()
        r = (a.get("a") or "").lower()
        if "combien" in q or "montant" in q or "emprunter" in q:
            nums = _extract_numbers(r)
            if nums:
                return nums[0]
    return 0


def _compute_realistic_max(monthly_revenue: int, has_collateral: bool, amount_wanted: int) -> int:
    cap = 24 if has_collateral else 6
    realistic = monthly_revenue * cap
    if realistic < 50000:
        realistic = 50000
    capped = min(amount_wanted, realistic) if amount_wanted > 0 else realistic
    return capped


# ==============================================================
# SCORING
# ==============================================================

def _extract_activity_duration(answers: list[dict]) -> tuple[int, str]:
    for a in answers:
        q = (a.get("q") or "").lower()
        r = (a.get("a") or "").lower()
        if "combien de temps" in q or "depuis combien" in q:
            nums = _extract_numbers(r)
            if nums:
                v = nums[0]
                if any(w in r for w in ["mois"]):
                    return v, "mois"
                if any(w in r for w in ["an", "annee", "ans"]):
                    return v * 12, "ans"
                return v, "mois"
    return 0, ""


def _extract_credit_history(answers: list[dict]) -> str:
    for a in answers:
        q = (a.get("q") or "").lower()
        r = (a.get("a") or "").lower()
        if "deja eu un credit" in q or "historique" in q:
            if any(w in r for w in ["oui", "deja", "rembourse"]):
                if any(w in r for w in ["bien", "rembourse", "temps"]):
                    return "bon"
                return "moyen"
            return "aucun"
    return "non precise"


def _extract_savings(answers: list[dict]) -> bool:
    for a in answers:
        q = (a.get("q") or "").lower()
        r = (a.get("a") or "").lower()
        if "epargne" in q:
            return any(w in r for w in ["oui", "epargne", "compte", "economie"])
    return False


def score_from_answers(answers: list[dict], document_extractions: list[dict] = None) -> dict:
    description = ""
    for a in answers:
        if "decris" in (a.get("q") or "").lower()[:8]:
            description = a.get("a", "")

    monthly_income = _estimate_monthly_revenue(answers)
    amount_wanted = _extract_amount_wanted(description, answers)
    duration_months, duration_unit = _extract_activity_duration(answers)
    credit_history = _extract_credit_history(answers)
    has_savings = _extract_savings(answers)

    has_collateral = False
    for a in answers:
        r = (a.get("a") or "").lower()
        if "garantie" in (a.get("q") or "").lower() and "oui" in r:
            has_collateral = True
        if "garantie" in r and ("terrain" in r or "boutique" in r or "maison" in r or "vehicule" in r or "oui" in r or "iphone" in r):
            has_collateral = True

    business_reg = _extract_business_registration(answers)
    sector = _extract_sector(answers)

    realistic_max = _compute_realistic_max(monthly_income, has_collateral, amount_wanted)

    # Risk preliminaire multi-facteurs
    risk = "Eleve"
    if monthly_income >= 200000:
        risk = "Moyen"
    if monthly_income >= 500000 and has_collateral:
        risk = "Faible"
    if monthly_income >= 1000000:
        risk = "Faible"
    if credit_history == "bon" and risk == "Moyen":
        risk = "Faible"
    if duration_months >= 12:
        if risk == "Eleve":
            risk = "Moyen"

    prompt = _build_groq_prompt(answers, monthly_income, amount_wanted, has_collateral,
                                realistic_max, risk, sector, duration_months,
                                credit_history, has_savings, business_reg,
                                document_extractions=document_extractions)
    resp = client.chat.completions.create(
        model=SCORE_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.1,
        max_tokens=1024,
    )
    data = json.loads(resp.choices[0].message.content)
    data["model"] = SCORE_MODEL
    data["tokens_used"] = getattr(resp.usage, "total_tokens", 0)
    data["max_amount"] = realistic_max

    _log(f"Groq score OK: {data.get('score')}, risk: {data.get('risk')}, tokens: {data['tokens_used']}")
    return data


def _build_groq_prompt(answers: list[dict], income: int, wanted: int, collateral: bool,
                       realistic_max: int, risk_label: str, sector: str,
                       duration_months: int, credit_history: str,
                       has_savings: bool, business_reg: bool,
                       document_extractions: list[dict] = None) -> str:
    compacted = _compact_history(answers)
    qa = "\n".join(f"- {a.get('q', '')}: {a.get('a', '')}" for a in compacted)

    ratio = round((wanted / income) * 100) if income > 0 else 0

    docs_ctx = ""
    if document_extractions:
        doc_lines = []
        for d in document_extractions:
            relevant = {k: v for k, v in d.items() if k != "error" and not k.startswith("_")}
            if relevant:
                doc_lines.append(json.dumps(relevant, ensure_ascii=False))
        if doc_lines:
            docs_ctx = "\nDocuments fournis par le client:\n" + "\n".join(f"- {l}" for l in doc_lines) + "\n\n"

    return f"""Tu es un analyste de credit pour le marche UEMOA (Afrique de l'Ouest). Analyse CE profil precis.

Profil:
{qa}

Revenu mensuel: {income} FCFA
Montant demande: {wanted} FCFA
Ratio demande/revenu: {ratio}%
Secteur: {sector}
Duree activite: {duration_months} mois
Collateral: {"oui" if collateral else "non"}
RC/Patente: {"oui" if business_reg else "non"}
Historique credit: {credit_history}
Epargne: {"oui" if has_savings else "non"}
Montant realiste max: {realistic_max} FCFA
Risque preliminaire: {risk_label}
{docs_ctx}REGLES UEMOA:
- Le marche informel represente ~80% de l'economie: absence de bulletin de salaire n'est pas un risque
- Sans collateral: pret max = 6x revenu mensuel. Avec collateral: jusqu'a 24x
- La mensualite ne doit pas exceder 40% du revenu mensuel
- Taux directeurs: banques 8-18%, microfinances 10-24%, fintechs 24-60%

INSTRUCTIONS STRICTES:
1. Score 0-100 base sur: ratio remboursement, secteur, collateral, anciennete, historique credit, epargne
2. Un ratio demande/revenu > 50% penalise fortement le score
3. Un historique credit "bon" augmente le score
4. L'epargne est un signal positif
5. analysis: SPECIFIQUE au profil (secteur, montant, revenu, anciennete). Cite les chiffres exacts.
6. missing_documents: adaptes au profil (pas de bulletins si informel)
7. improvement_tips: 2-3 conseils SPECIFIQUES actionnables

Retourne CE JSON:
{{
  "score": 65,
  "risk": "Moyen",
  "analysis": "Texte specifique de 2-3 phrases qui cite les chiffres du profil.",
  "missing_documents": ["piece_identite", "preuve_revenus"],
  "improvement_tips": ["Conseil 1 specifique", "Conseil 2 specifique"],
  "confidence": 0.85
}}

IMPORTANT: score entre 0 et 100. Sois REALISTE: un petit commerçant avec 150K revenu et 500K demande sans garantie = score bas (~30-45). Un profil stable avec garantie = 60-80."""



# ==============================================================
# CHAT / QUESTIONS — LLM decide combien et quoi demander
# ==============================================================

CTX_LIMIT = 128000
CTX_TARGET = 75000


def _estimate_tokens(text: str) -> int:
    return len(text) // 4


def _compact_history(answers: list[dict]) -> list[dict]:
    full = "\n".join(f"Q: {a.get('q','')}\nR: {a.get('a','')}" for a in answers)
    if _estimate_tokens(full) < CTX_TARGET:
        return answers
    covered = {}
    for a in answers:
        covered[a.get("q", "")[:30]] = a.get("a", "")
    summary = "; ".join(f"{k} => {v[:80]}" for k, v in covered.items())
    recent = answers[-3:]
    return [{"q": "--- RESUME PROFIL ---", "a": summary}] + recent


def build_first_question() -> str:
    return "Decris-moi ton projet ou besoin en quelques phrases : quel secteur, pourquoi ce pret, quelle est ta situation ?"


def build_questionnaire(project_desc: str) -> list[str]:
    """LLM genere un questionnaire personnalise."""
    nums = _extract_numbers(project_desc)
    amount_hint = max(nums) if nums else 500000
    sector_hint = ""
    for w in ["commerce", "agriculture", "service", "artisanat", "tech", "ia", "numerique"]:
        if w in project_desc.lower():
            sector_hint = w
            break
    try:
        all_partners, all_products, all_rules = _get_all_partners()
    except Exception:
        all_partners, all_products, all_rules = _get_partners(amount_hint, sector_hint)
    partners = all_partners or []
    products = all_products or []
    rules = all_rules or []

    partners_ctx = "\n".join(
        f"- {p['name']} ({p['type']}): {p['min_amount']:,}-{p['max_amount']:,} FCFA, taux {p['rate']}. Docs requis: {', '.join(p['docs'] or [])}."
        for p in partners[:8]
    ) if partners else "Aucun partenaire trouve."

    products_ctx = "\n".join(
        f"- {pr['partner']} > {pr['product']}: {pr['min_amount']:,}-{pr['max_amount']:,} FCFA, {pr['min_duration']}-{pr['max_duration']}mois, taux {pr['annual_rate']}%. Garantie: {'oui' if pr['collateral_required'] else 'non'}. Req: {', '.join(pr['requirements'] or [])}."
        for pr in products[:8]
    ) if products else ""

    rules_ctx = "\n".join(
        f"  [{r['category']}] {r['title']}: {r['content']}"
        for r in rules[:8]
    ) if rules else ""

    prompt = f"""Le client a decrit son projet: "{project_desc}"

--- PARTENAIRES DISPONIBLES (avec conditions) ---
{partners_ctx}

--- PRODUITS DE CREDIT (avec conditions) ---
{products_ctx}

--- REGLES METIER ---
{rules_ctx}

Genere un questionnaire personnalise en BLOCS de questions.

Chaque bloc porte sur UN theme (ex: informations personnelles, finance, documents, garanties).
Regroupe les questions par theme : chaque bloc = 2 a 4 questions liees entre elles.

Exemple:
{{
  "blocks": [
    ["Question 1 ?", "Question 2 ?", "Question 3 ?"],
    ["Question 4 ?", "Question 5 ?"],
    ["Question 6 ?", "Question 7 ?", "Question 8 ?"]
  ]
}}

Chaque question verifie UN critere precis des partenaires (montant, duree, garantie, documents, secteur, historique, revenu).
Questions en francais, "tu". 5 a 8 questions total. Chaque question < 15 mots."""

    try:
        resp = client.chat.completions.create(
            model=SCORE_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=600,
        )
        raw = resp.choices[0].message.content
        # Try to extract JSON from response
        start = raw.find('{')
        end = raw.rfind('}') + 1
        if start >= 0 and end > start:
            raw = raw[start:end]
        data = json.loads(raw)
        if isinstance(data, dict):
            blocks = data.get("blocks") or data.get("questions") or data.get("blocs") or None
            if blocks and isinstance(blocks, list):
                flat = [q for block in blocks for q in block]
                if flat:
                    return flat
        if isinstance(data, list):
            return data
        for v in data.values():
            if isinstance(v, list):
                return v
    except Exception:
        _log("build_questionnaire LLM call failed, using fallback")
    return ["Quelle est ton activite ?", "Combien gagnes-tu par mois ?", "Combien veux-tu emprunter ?", "Depuis combien de temps ?", "As-tu des garanties ?", "As-tu deja eu un credit ?", "Quels documents peux-tu fournir ?"]


def build_questionnaire_blocks(project_desc: str) -> dict:
    """Retourne {blocks: [[q1,q2],[q3,q4,q5],...]} pour le frontend progressif."""
    try:
        return _build_questionnaire_blocks(project_desc)
    except Exception as e:
        _log(f"build_questionnaire_blocks UNEXPECTED: {e}")
        raise

def _build_questionnaire_blocks(project_desc: str) -> dict:
    _log("build_questionnaire_blocks: step 1 extract_numbers")
    nums = _extract_numbers(project_desc)
    amount_hint = max(nums) if nums else 500000
    sector_hint = ""
    for w in ["commerce", "agriculture", "service", "artisanat", "tech", "ia", "numerique"]:
        if w in project_desc.lower():
            sector_hint = w
            break
    _log(f"build_questionnaire_blocks: step 2 get_partners hint={amount_hint} sector={sector_hint}")
    try:
        all_partners, all_products, all_rules = _get_all_partners()
    except Exception:
        all_partners, all_products, all_rules = _get_partners(amount_hint, sector_hint)
    partners = all_partners or []
    products = all_products or []
    rules = all_rules or []
    _log(f"build_questionnaire_blocks: got {len(partners)} partners, {len(products)} products")

    _log("build_questionnaire_blocks: step 3 format context")
    partners_ctx = "\n".join(
        f"- {p['name']} ({p['type']}): {p['min_amount']:,}-{p['max_amount']:,} FCFA, taux {p['rate']}. Docs requis: {', '.join(p['docs'] or [])}."
        for p in partners[:8]
    ) if partners else "Aucun partenaire trouve."

    products_ctx = "\n".join(
        f"- {pr['partner']} > {pr['product']}: {pr['min_amount']:,}-{pr['max_amount']:,} FCFA, {pr['min_duration']}-{pr['max_duration']}mois, taux {pr['annual_rate']}%. Garantie: {'oui' if pr['collateral_required'] else 'non'}. Req: {', '.join(pr['requirements'] or [])}."
        for pr in products[:8]
    ) if products else ""

    rules_ctx = "\n".join(
        f"  [{r['category']}] {r['title']}: {r['content']}"
        for r in rules[:8]
    ) if rules else ""

    _log("build_questionnaire_blocks: step 4 LLM call")
    prompt_text = f"""Projet: "{project_desc}"

Partenaires:
{partners_ctx}

Produits:
{products_ctx}

Regles:
{rules_ctx}

Genere un questionnaire en BLOCS. Chaque bloc = 2 a 4 questions sur UN theme.
{{
  "blocks": [["Q1 ?","Q2 ?"],["Q3 ?","Q4 ?","Q5 ?"]]
}}
5 a 8 questions. Francais, "tu"."""
    try:
        resp = client.chat.completions.create(
            model=SCORE_MODEL,
            messages=[{"role": "user", "content": prompt_text}],
            temperature=0.7,
            max_tokens=600,
        )
        raw = resp.choices[0].message.content
        start = raw.find('{')
        end = raw.rfind('}') + 1
        if start >= 0 and end > start:
            raw = raw[start:end]
        data = json.loads(raw)
        if isinstance(data, dict):
            blocks = data.get("blocks") or data.get("questions") or data.get("blocs") or None
            if blocks and isinstance(blocks, list) and len(blocks) > 0 and isinstance(blocks[0], list):
                _log(f"build_questionnaire_blocks: LLM returned {len(blocks)} blocks")
                return {"blocks": blocks}
    except Exception as e:
        _log(f"build_questionnaire_blocks LLM call failed: {e}")

    _log("build_questionnaire_blocks: step 5 fallback build_questionnaire")
    flat = build_questionnaire(project_desc)
    _log(f"build_questionnaire_blocks: fallback returned {len(flat)} questions")
    return {"blocks": [flat[i:i+3] for i in range(0, len(flat), 3)]}





_last_questions: list[str] = []

_FALLBACK_QUESTIONS = [
    "Quel est ton revenu mensuel moyen ?",
    "Depuis combien de temps exerces-tu ?",
    "Quel montant souhaites-tu emprunter ?",
    "As-tu des garanties a proposer ?",
    "As-tu deja eu un credit ?",
    "As-tu une epargne ?",
    "Quelle est la destination du pret ?",
    "Peux-tu fournir des documents (piece d identite, justificatif de revenus) ?",
]

def build_next_question(answers: list[dict]) -> str:
    """LLM decide: infos suffisantes (DONE), clarification, ou demande document."""
    global _last_questions
    context = _compact_history(answers)
    hist = "\n".join(f"Q: {a.get('q','')}\nR: {a.get('a','')}" for a in context)

    prompt = f"""Tu es un conseiller credit. Le client a repondu:
{hist}

Il te faut au moins: activite, revenu, montant, duree, garantie.
Si toutes ces infos sont presentes (memes partielles), reponds: DONE
Sinon, pose UNE question courte. Max 12 mots. Naturel, en "tu"."""

    try:
        resp = client.chat.completions.create(
            model=SCORE_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=80,
        )
        q = resp.choices[0].message.content.strip().strip('"').strip("'")
    except Exception as e:
        _log(f"build_next_question Groq failed: {e}")
        return _fallback_question(answers)

    if "DONE" in q.upper() and len(q) < 10:
        _last_questions.clear()
        return "DONE"

    # Loop detection: same question asked 2+ times → force DONE
    if len(_last_questions) >= 2 and all(q == prev for prev in _last_questions[-2:]):
        _last_questions.clear()
        return "DONE"
    _last_questions.append(q)
    if len(_last_questions) > 10:
        _last_questions.pop(0)

    return q if q else "Peux-tu preciser ?"


def _fallback_question(answers: list[dict]) -> str:
    """Fallback quand Groq est down: pose les questions manquantes une par une."""
    asked_topics = set()
    for a in answers:
        q = (a.get("q") or "").lower()
        r = (a.get("a") or "").lower()
        asked_topics.add(q[:40])
        if "gagnes" in q or "revenu" in q:
            asked_topics.add("revenu")
        if "combien" in q or "montant" in q or "emprunter" in q:
            asked_topics.add("montant")
        if "temps" in q or "depuis" in q:
            asked_topics.add("duree")
        if "garantie" in q:
            asked_topics.add("garantie")
        if "credit" in q or "deja" in q:
            asked_topics.add("credit")
        if "epargne" in q:
            asked_topics.add("epargne")
        if "destination" in q or "quoi" in q:
            asked_topics.add("destination")
    if "revenu" not in asked_topics:
        return "Quel est ton revenu mensuel moyen ?"
    if "montant" not in asked_topics:
        return "Quel montant souhaites-tu emprunter ?"
    if "duree" not in asked_topics:
        return "Depuis combien de temps exerces-tu ?"
    if "garantie" not in asked_topics:
        return "As-tu des garanties a proposer ?"
    if "credit" not in asked_topics:
        return "As-tu deja eu un credit ?"
    if "epargne" not in asked_topics:
        return "As-tu une epargne ?"
    if "destination" not in asked_topics:
        return "Quelle est la destination du pret ?"
    return "DONE"

# ==============================================================
# DOCUMENT REQUESTS — LLM decide quoi demander selon profil + partenaires
# ==============================================================

def build_document_requests(answers: list[dict]) -> list[dict]:
    """LLM analyse le profil + les conditions partenaires et decide quels documents demander."""
    try:
        all_partners, all_products, all_rules = _get_all_partners()
    except Exception:
        return []
    if not all_partners:
        return []
    profile = "\n".join(f"- {a.get('q','')}: {a.get('a','')}" for a in answers)
    partners_ctx = "\n".join(
        f"- {p['name']} ({p['type']}): docs requis: {', '.join(p['docs'] or [])}. Secteurs: {', '.join(p['sectors'] or [])}."
        for p in all_partners[:10]
    )
    products_ctx = "\n".join(
        f"- {pr['partner']} > {pr['product']}: collateral={'oui' if pr.get('collateral_required') else 'non'}. Req: {', '.join(pr['requirements'] or [])}."
        for pr in all_products[:10]
    )
    prompt = f"""Tu es un conseiller credit UEMOA. Voici le profil du client et les conditions partenaires.

PROFIL CLIENT:
{profile}

PARTENAIRES ET LEURS DOCUMENTS REQUIS:
{partners_ctx}

PRODUITS ET LEURS EXIGENCES:
{products_ctx}

Decide quels documents demander a CE client precis, en fonction de:
1. Son secteur d'activite, son revenu, le montant demande
2. Les documents requis par les partenaires compatibles avec son profil
3. Ce qui est realiste pour son profil (pas de bulletin de salaire si informel)

Retourne CE JSON:
{{
  "requests": [
    {{
      "doc_type": "business_photo",
      "label": "Photo de ta boutique ou commerce",
      "reason": "Pour les partenaires qui financent le commerce",
      "optional": false
    }},
    {{
      "doc_type": "id_card",
      "label": "Ta piece d'identite",
      "reason": "Document de base requis par tous les partenaires",
      "optional": false
    }}
  ]
}}

Regles:
- Prioritaires: ceux qui debloquent le plus de partenaires.
- Si le profil est informel: photo_activite et id_card sont les plus utiles.
- Si le profil a des garanties: photo garantie ou titre de propriete.
- Si le profil a un RC/patente: business_license.
- Si le profil a deja un historique credit: relevé bancaire ou preuve.
- Chaque document doit avoir un label clair en francais, "tu".
- optional: true si le document est utile mais pas bloquant.
- Ne demande que les documents vraiment pertinents pour CE profil precis et CES partenaires."""

    try:
        resp = client.chat.completions.create(
            model=SCORE_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=800,
        )
        data = json.loads(resp.choices[0].message.content)
        requests = data.get("requests", [])
        if isinstance(requests, list) and len(requests) > 0:
            _log(f"build_document_requests: {len(requests)} documents demandes")
            return requests
    except Exception as e:
        _log(f"build_document_requests failed: {e}")
    return []


# ==============================================================
# DOCUMENT EXTRACTION (Vision)
# ==============================================================

EXTRACT_PROMPTS = {
    "id_card": "Extrais en JSON: nom, prenom, date_naissance, numero_piece, date_expiration, sexe",
    "bank_statement": "Extrais en JSON: institution, solde_actuel, periode, entrees_total, sorties_total",
    "business_license": "Extrais en JSON: nom_entreprise, numero_rcm, date_creation, siege, activite",
    "selfie": "Retourne JSON: detection_visage (bool), qualite (bonne/moyenne/mauvaise)",
    "receipt": "Extrais en JSON: montant, date, fournisseur, description",
    "proof_of_address": "Extrais en JSON: nom, adresse, type_facture, date",
    "business_photo": "Decris en JSON: type_commerce, taille (petite/moyenne/grande), etat (bon/moyen/mauvais)",
    "photo_activite": "Decris en JSON: type_activite, equipement, professionnalisme (faible/moyen/eleve)",
}


def extract_document_fields(image_url: str, doc_type: str) -> dict:
    prompt = EXTRACT_PROMPTS.get(doc_type, f"Extrais les infos de ce document en JSON. Type: {doc_type}")
    try:
        resp = client.chat.completions.create(
            model=VISION_MODEL,
            messages=[{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": image_url}}]}],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=1024,
        )
        return json.loads(resp.choices[0].message.content)
    except Exception as e:
        _log(f"Vision failed: {e}")
        return {"error": str(e), "doc_type": doc_type}


# ==============================================================
# COUCHE 1 — Comparateur exhaustif multi-institutions
# ==============================================================

def _get_all_partners(country: str = "TG") -> tuple[list[dict], list[dict], list[dict]]:
    """Retourne TOUS les partenaires actifs (sans LIMIT), leurs produits ET les regles."""
    dsn = os.environ.get("NEON_DSN", "") or NEON_DSN
    if not dsn:
        return [], [], []
    try:
        conn = psycopg2.connect(dsn)
        cur = conn.cursor()
        cur.execute(
            """SELECT name, type, min_amount, max_amount, rate, sectors, docs, description, base_rate, max_rate, id
               FROM partners
               WHERE countries @> ARRAY[%s]::TEXT[]
               ORDER BY name ASC""",
            (country,)
        )
        def _to_num(v):
            return float(v) if v is not None else None

        partners = []
        partner_ids = []
        for r in cur.fetchall():
            partners.append({
                "name": r[0], "type": r[1], "min_amount": r[2], "max_amount": r[3],
                "rate": str(r[4] or ""),
                "sectors": r[5], "docs": r[6], "description": r[7],
                "base_rate": _to_num(r[8]) if r[8] is not None else None,
                "max_rate": _to_num(r[9]) if r[9] is not None else None,
            })
            partner_ids.append(r[10])

        products = []
        if partner_ids:
            cur.execute(
                """SELECT p.name AS partner_name, pr.name, pr.min_amount, pr.max_amount,
                          pr.min_duration_months, pr.max_duration_months, pr.annual_rate,
                          pr.collateral_required, pr.requirements, pr.description
                   FROM products pr JOIN partners p ON p.id = pr.partner_id
                   WHERE pr.partner_id = ANY(%s)
                   ORDER BY pr.annual_rate ASC""",
                (partner_ids,)
            )
            for r in cur.fetchall():
                products.append({
                    "partner": r[0], "product": r[1], "min_amount": r[2], "max_amount": r[3],
                    "min_duration": r[4], "max_duration": r[5], "annual_rate": _to_num(r[6]),
                    "collateral_required": r[7], "requirements": r[8], "description": r[9],
                })

        cur.execute(
            """SELECT category, title, content FROM knowledge_base ORDER BY category LIMIT 20"""
        )
        rules = [{"category": r[0], "title": r[1], "content": r[2]} for r in cur.fetchall()]

        conn.close()
        return partners, products, rules
    except Exception as e:
        _log(f"_get_all_partners failed: {e}")
        return [], [], []


def _extract_sector(answers: list[dict]) -> str:
    text = " ".join(a.get("a", "") for a in answers).lower()
    sectors = {
        "commerce": ["commerce", "vente", "boutique", "magasin", "grossiste", "detail"],
        "agriculture": ["agriculture", "ferme", "champ", "elevage", "plantation", "culture"],
        "service": ["service", "transport", "restaurant", "coiffure", "hotel", "logistique"],
        "artisanat": ["artisan", "atelier", "couture", "menuiserie", "mecanique"],
        "industrie": ["industrie", "production", "fabrication", "usine"],
        "tech": ["tech", "ia", "numerique", "informatique", "developpement"],
    }
    for sector, keywords in sectors.items():
        if any(kw in text for kw in keywords):
            return sector
    for a in answers:
        q = (a.get("q") or "").lower()
        if "secteur" in q or "activite" in q:
            return a.get("a", "").strip()[:30] or "non precise"
    return "non precise"


def _extract_has_collateral(answers: list[dict]) -> bool:
    for a in answers:
        r = (a.get("a") or "").lower()
        q = (a.get("q") or "").lower()
        if "garantie" in q and "non" in r:
            return False
        if "garantie" in r and any(w in r for w in ["terrain", "boutique", "maison", "vehicule", "oui"]):
            return True
    return False


def _extract_country(answers: list[dict]) -> str:
    text = " ".join(a.get("a", "") for a in answers).lower()
    mapping = {
        "tg": ["togo", "lome", "lom\u00e9"],
        "bj": ["benin", "cotonou", "porto-novo"],
        "ci": ["c\u00f4te d'ivoire", "cote d'ivoire", "abidjan", "bouak\u00e9", "bouake", "yamoussoukro"],
        "sn": ["senegal", "dakar", "saint-louis"],
        "ml": ["mali", "bamako"],
        "bf": ["burkina", "ouagadougou", "bobo-dioulasso"],
        "ne": ["niger", "niamey"],
        "gw": ["guin\u00e9e-bissau", "guinee-bissau", "bissau"],
    }
    for code, keywords in mapping.items():
        if any(kw in text for kw in keywords):
            return code.upper()
    return "TG"


def _extract_business_registration(answers: list[dict]) -> bool:
    for a in answers:
        r = (a.get("a") or "").lower()
        q = (a.get("q") or "").lower()
        if "registre" in q or "rc" in q or "patente" in q:
            return "oui" in r or "rc" in r or "patente" in r
    return False


# ==============================================================
# COUCHE 2 — Matching intelligent LLM
# ==============================================================

def _layer2_enrich(answers: list[dict], report: dict,
                   partners: list[dict], products: list[dict]) -> dict:
    """Enrichit le rapport avec une analyse LLM : meilleur match,
    mensualites estimees, comparatif personnalise."""
    top = report.get("top_recommendations", [])[:3]
    if not top:
        return {"recommendations": [], "summary": report.get("analysis", "")}

    profil = report["profil"]
    income = profil["monthly_income"]
    wanted = profil["amount_wanted"]
    sector = profil["sector"]

    partners_ctx = "\n".join(
        f"- {p['name']} ({p['type']}): {p['min_amount']:,}-{p['max_amount']:,} FCFA, taux {p['rate']}"
        for p in top
    )

    products_ctx = "\n".join(
        f"- {pr['partner']} > {pr['product']}: max {pr['max_amount']:,} FCFA, {pr['min_duration']}-{pr['max_duration']}mois, taux {pr['annual_rate']}%"
        for pr in products[:10]
    ) if products else ""

    user_profile = "\n".join(f"- {a.get('q','')}: {a.get('a','')}" for a in answers)

    prompt = f"""Tu es un conseiller credit UEMOA. Voici le profil et les partenaires disponibles.

PROFIL:
{user_profile}

Revenu: {income:,} FCFA/mois
Montant souhaite: {wanted:,} FCFA
Secteur: {sector}

PARTENAIRES ELIGIBLES:
{partners_ctx}

PRODUITS:
{products_ctx}

Pour chaque partenaire, estime:
1. La mensualite sur 12 mois (taux suppose = moyenne du partenaire)
2. Le taux approximatif selon le profil
3. Pourquoi ce partenaire est adapte (ou pas) à CE profil precis

Retourne CE JSON:
{{
  "summary": "Paragraphe comparatif de 3-4 phrases. Compare les options. Recommande la meilleure.",
  "best_match": "Nom du meilleur partenaire",
  "best_reason": "Pourquoi c'est le meilleur choix pour ce profil precis (2-3 phrases)",
  "recommendations": [
    {{
      "name": "Nom partenaire",
      "estimated_rate": 12.0,
      "estimated_monthly": 45000,
      "estimated_total": 540000,
      "why": "Pourquoi ce partenaire pour ce profil (1-2 phrases)"
    }}
  ]
}}

Francais. Sois SPECIFIQUE au profil (cite les chiffres du client)."""
    resp = client.chat.completions.create(
        model=SCORE_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.2,
        max_tokens=1024,
    )
    data = json.loads(resp.choices[0].message.content)

    for rec in data.get("recommendations", []):
        rname = rec.get("name", "")
        for p in top:
            if p["name"] == rname:
                rec["match_percent"] = p.get("match_percent")
                rec["type"] = p.get("type")
                rec["products"] = p.get("products", [])
                break

    return data


def build_comparison_report(answers: list[dict], document_extractions: list[dict] = None) -> dict:
    country = _extract_country(answers)
    partners, products, _ = _get_all_partners(country)
    monthly_income = _estimate_monthly_revenue(answers)
    amount_wanted = _extract_amount_wanted("", answers)
    sector = _extract_sector(answers)
    collateral = _extract_has_collateral(answers)
    business_reg = _extract_business_registration(answers)
    realistic_max = _compute_realistic_max(monthly_income, collateral, amount_wanted)
    score_data = score_from_answers(answers, document_extractions)
    score = score_data.get("score", 0)
    risk = score_data.get("risk", "N/A")
    analysis = score_data.get("analysis", "")
    missing_docs = score_data.get("missing_documents", [])
    tips = score_data.get("improvement_tips", [])

    if amount_wanted == 0:
        amount_wanted = 500000

    # Grouper les produits par partenaire
    products_by_partner = {}
    for pr in products:
        pn = pr["partner"]
        if pn not in products_by_partner:
            products_by_partner[pn] = []
        products_by_partner[pn].append({
            "name": pr["product"],
            "min_amount": pr["min_amount"],
            "max_amount": pr["max_amount"],
            "rate": pr["annual_rate"],
        })

    all_comparisons = []
    eligible_count = 0
    partial_count = 0
    not_eligible_count = 0

    for p in partners:
        issues = []
        strengths = []
        match_score = 0

        p_min = p["min_amount"] or 0
        p_max = p["max_amount"] or float("inf")

        # Amount check
        if p_min > 0 and amount_wanted < p_min:
            issues.append(f"Montant minimum {p_min:,} FCFA > {amount_wanted:,} FCFA demande")
        elif p_max < float("inf") and amount_wanted > p_max:
            issues.append(f"Montant maximum {p_max:,} FCFA < {amount_wanted:,} FCFA demande")
        else:
            match_score += 30
            strengths.append(f"Montant compatible ({p_min:,}-{p_max:,} FCFA)")

        # Sector check
        if p["sectors"] and sector not in ["non precise"]:
            p_sectors = [s.strip().lower() for s in p["sectors"]]
            if sector.lower() in p_sectors:
                match_score += 25
                strengths.append(f"Secteur '{sector}' finance")
            else:
                issues.append(f"Secteur '{sector}' non couvert")

        # Collateral check
        if collateral:
            match_score += 15
            strengths.append("Garantie disponible")
        else:
            pass  # on ne penalise pas l'absence de garantie

        # Business registration check
        if business_reg:
            match_score += 10
            strengths.append("RC/Patente disponible")

        # Docs readiness
        if p["docs"]:
            match_score += 10
            strengths.append(f"Documents requis: {', '.join(p['docs'][:3])}")

        # Risk/compatibility
        if p["description"] and sector not in ["non precise"]:
            desc = p["description"].lower()
            if sector.lower() in desc:
                match_score += 10

        # Cap at 100
        match_score = min(match_score, 100)

        status = "eligible" if match_score >= 60 else ("partial" if match_score >= 30 else "not_eligible")
        if status == "eligible":
            eligible_count += 1
        elif status == "partial":
            partial_count += 1
        else:
            not_eligible_count += 1

        prs = products_by_partner.get(p["name"], [])
        all_comparisons.append({
            "name": p["name"],
            "type": p["type"],
            "min_amount": p["min_amount"],
            "max_amount": p["max_amount"],
            "rate": p["rate"],
            "status": status,
            "match_percent": match_score,
            "strengths": strengths[:3],
            "issues": issues[:3],
            "products": prs[:3],
        })

    # Top recommendations = eligible triés par match_score
    top = sorted([c for c in all_comparisons if c["status"] == "eligible"], key=lambda x: x["match_percent"], reverse=True)[:5]

    report = {
        "total_institutions": len(partners),
        "eligible_count": eligible_count,
        "partial_count": partial_count,
        "not_eligible_count": not_eligible_count,
        "score": score,
        "risk": risk,
        "analysis": analysis,
        "missing_documents": missing_docs,
        "improvement_tips": tips,
        "max_amount": realistic_max,
        "profil": {
            "monthly_income": monthly_income,
            "amount_wanted": amount_wanted,
            "realistic_max": realistic_max,
            "sector": sector,
            "collateral": collateral,
            "business_registration": business_reg,
        },
        "top_recommendations": top,
        "all_comparisons": all_comparisons,
    }

    try:
        enriched = _layer2_enrich(answers, report, partners, products)
        report["layer2"] = enriched
    except Exception as e:
        _log(f"layer2 enrich failed: {e}")
        report["layer2"] = {"recommendations": top, "summary": analysis}

    return report
