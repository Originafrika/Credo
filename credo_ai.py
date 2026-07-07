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

def score_from_answers(answers: list[dict]) -> dict:
    description = ""
    for a in answers:
        if "decris" in (a.get("q") or "").lower()[:8]:
            description = a.get("a", "")

    monthly_income = _estimate_monthly_revenue(answers)
    amount_wanted = _extract_amount_wanted(description, answers)

    has_collateral = False
    for a in answers:
        r = (a.get("a") or "").lower()
        if "garantie" in (a.get("q") or "").lower() and "oui" in r:
            has_collateral = True
        if "garantie" in r and ("terrain" in r or "boutique" in r or "maison" in r or "vehicule" in r or "oui" in r or "iphone" in r):
            has_collateral = True

    realistic_max = _compute_realistic_max(monthly_income, has_collateral, amount_wanted)
    risk = "Eleve"
    if has_collateral and monthly_income >= 200000:
        risk = "Moyen"
    if has_collateral and monthly_income >= 500000:
        risk = "Faible"

    prompt = _build_groq_prompt(answers, monthly_income, amount_wanted, has_collateral, realistic_max, risk)
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


def _build_groq_prompt(answers: list[dict], income: int, wanted: int, collateral: bool, realistic_max: int, risk_label: str) -> str:
    compacted = _compact_history(answers)
    qa = "\n".join(f"- {a.get('q', '')}: {a.get('a', '')}" for a in compacted)

    return f"""Tu es un analyste de credit pour le marche UEMOA. Analyse CE profil precis.

Profil:
{qa}

Revenu mensuel: {income} FCFA
Montant demande: {wanted} FCFA
Collateral: {"oui" if collateral else "non"}
Risque preliminaire: {risk_label}

INSTRUCTIONS STRICTES:
1. Score base sur: remboursement possible (max 50% du revenu), secteur, collateral, historique
2. analysis: cite les chiffres du profil (secteur, montant demande, revenu, collateral)
3. missing_documents: liste les documents manquants types (piece identite, justificatif revenu, garantie)
4. improvement_tips: SPECIFIQUES a ce profil, pas generiques

Retourne CE JSON:
{{
  "score": 420,
  "risk": "Eleve",
  "analysis": "2-3 phrases SPECIFIQUES. Cite secteur, montant, revenu. Explique le verdict.",
  "missing_documents": ["piece_identite"],
  "improvement_tips": ["Conseil SPECIFIQUE"],
  "confidence": 0.85
}}"""



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
    partners, products, rules = _get_partners(amount_hint, sector_hint)

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
    partners, products, rules = _get_partners(amount_hint, sector_hint)
    _log(f"build_questionnaire_blocks: got {len(partners)} partners, {len(products)} products, {len(rules)} rules")

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





def build_next_question(answers: list[dict]) -> str:
    """LLM decide: infos suffisantes (DONE), clarification, ou demande document."""
    context = _compact_history(answers)
    hist = "\n".join(f"Q: {a.get('q','')}\nR: {a.get('a','')}" for a in context)

    prompt = f"""Tu es un conseiller credit. Le client a repondu:
{hist}

Il te faut au moins: activite, revenu, montant, duree, garantie.
Si toutes ces infos sont presentes (memes partielles), reponds: DONE
Sinon, pose UNE question courte. Max 12 mots. Naturel, en "tu"."""

    resp = client.chat.completions.create(
        model=SCORE_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5,
        max_tokens=80,
    )
    q = resp.choices[0].message.content.strip().strip('"').strip("'")
    if "DONE" in q.upper() and len(q) < 10:
        return "DONE"
    return q if q else "Peux-tu preciser ?"

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

def _get_all_partners(country: str = "TG") -> tuple[list[dict], list[dict]]:
    """Retourne TOUS les partenaires actifs (sans LIMIT) et leurs produits."""
    if not NEON_DSN:
        return [], []
    try:
        conn = psycopg2.connect(NEON_DSN)
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
                "rate": _to_num(r[4]), "sectors": r[5], "docs": r[6], "description": r[7],
                "base_rate": _to_num(r[8]), "max_rate": _to_num(r[9]),
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
        conn.close()
        return partners, products
    except Exception as e:
        _log(f"_get_all_partners failed: {e}")
        return [], []


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
            return code
    return "TG"


def _extract_business_registration(answers: list[dict]) -> bool:
    for a in answers:
        r = (a.get("a") or "").lower()
        q = (a.get("q") or "").lower()
        if "registre" in q or "rc" in q or "patente" in q:
            return "oui" in r or "rc" in r or "patente" in r
    return False


def build_comparison_report(answers: list[dict]) -> dict:
    country = _extract_country(answers)
    partners, products = _get_all_partners(country)
    monthly_income = _estimate_monthly_revenue(answers)
    amount_wanted = _extract_amount_wanted("", answers)
    sector = _extract_sector(answers)
    collateral = _extract_has_collateral(answers)
    business_reg = _extract_business_registration(answers)
    realistic_max = _compute_realistic_max(monthly_income, collateral, amount_wanted)
    score_data = score_from_answers(answers)
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

    return {
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
