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
        if "gagne" in r or "salaire" in r or "revenu" in r:
            nums = _extract_numbers(r)
            if nums:
                return nums[0]
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

MFI_NAMES = ["fucec", "wages", "cofina", "baobab", "micro", "finance"]

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

    # Post-process: clamp max_amount to realistic_max
    if data.get("max_amount", 0) > realistic_max:
        data["max_amount"] = realistic_max

    # Post-process: if risk is Eleve, filter partners to MFI only
    risk_val = data.get("risk", "Eleve")
    partners = data.get("recommended_partners", [])
    if risk_val == "Eleve":
        data["recommended_partners"] = [
            p for p in partners
            if any(mfi in (p.get("name", "") or "").lower() for mfi in MFI_NAMES)
        ]
        # If no MFI partners matched, force default
        if not data["recommended_partners"]:
            data["recommended_partners"] = [
                {"name": "FUCEC-Togo", "product": "Credit Micro-Entreprise", "amount": min(realistic_max, 500000), "rate": "18%", "reason": "Microfinance adaptee aux profils sans garantie materielle, avec accompagnement personnalise."},
                {"name": "WAGES Togo", "product": "Credit Femmes", "amount": min(realistic_max, 300000), "rate": "20%", "reason": "Credit solidaire accessible sans garantie, ideal pour demarrage d'activite."},
                {"name": "Cofina Togo", "product": "Credit Rapid", "amount": min(realistic_max, 200000), "rate": "22%", "reason": "Credit de proximite sans garantie, remboursement flexible."},
            ]

    _log(f"Groq score OK: {data.get('score')}, max: {data.get('max_amount')}, risk: {data.get('risk')}, tokens: {data['tokens_used']}")
    return data


def _build_groq_prompt(answers: list[dict], income: int, wanted: int, collateral: bool, realistic_max: int, risk_label: str) -> str:
    compacted = _compact_history(answers)
    qa = "\n".join(f"- {a.get('q', '')}: {a.get('a', '')}" for a in compacted)

    sector_hint = ""
    for a in answers:
        r = (a.get("a") or "").lower()
        if any(w in r for w in ["commerce", "vente", "boutique"]):
            sector_hint = "commerce"
        elif any(w in r for w in ["agriculture", "ferme", "champ"]):
            sector_hint = "agriculture"
        elif any(w in r for w in ["service", "transport", "restaurant"]):
            sector_hint = "service"
        elif any(w in r for w in ["artisan", "atelier", "couture"]):
            sector_hint = "artisanat"

    partners, products, rules = _get_partners(realistic_max, sector_hint)

    partners_str = "\n".join(
        f"- {p['name']} ({p['type']}): {p['min_amount']:,}-{p['max_amount']:,} FCFA, taux {p['rate']}. Docs: {', '.join(p['docs'])}."
        for p in partners
    ) if partners else ""

    products_str = "\n".join(
        f"- {pr['product']} ({pr['partner']}): {pr['min_amount']:,}-{pr['max_amount']:,} FCFA, {pr['min_duration']}-{pr['max_duration']}mois, taux {pr['annual_rate']}%. Garantie: {'oui' if pr['collateral_required'] else 'non'}. Req: {', '.join(pr['requirements'])}."
        for pr in products[:8]
    ) if products else ""

    rules_str = "\n".join(
        f"  [{r['category']}] {r['title']}: {r['content']}"
        for r in rules[:6]
    ) if rules else ""

    return f"""Tu es un analyste de credit pour le marche UEMOA. Analyse CE profil precis.

Profil:
{qa}

Revenu mensuel: {income} FCFA
Montant demande: {wanted} FCFA
Collateral: {"oui" if collateral else "non"}
Montant realiste max: {realistic_max} FCFA (regle: {6 if not collateral else 24}x revenu mensuel)
Risque preliminaire: {risk_label}

--- PARTENAIRES DISPONIBLES ---
{partners_str}
--- PRODUITS DE CREDIT ---
{products_str}
--- REGLES METIER ---
{rules_str}

INSTRUCTIONS STRICTES:
1. max_amount NE PEUT PAS depasser {realistic_max} FCFA. C'est ABSOLU.
2. Score base sur: remboursement possible (max 50% du revenu), secteur, collateral, historique
3. Si risque = Eleve, recommande UNIQUEMENT des microfinances (FUCEC, WAGES, Cofina, BAOBAB) — JAMAIS de banques
4. Chaque partenaire doit avoir un produit specifique
5. analysis: cite les chiffres du profil (secteur, montant demande, revenu, collateral)
6. missing_documents: extraits des docs requis par les partenaires recommandes
7. improvement_tips: SPECIFIQUES a ce profil, pas generiques

Retourne CE JSON:
{{
  "score": 420,
  "risk": "Eleve",
  "max_amount": {realistic_max},
  "analysis": "2-3 phrases SPECIFIQUES. Cite secteur, montant, revenu. Explique le verdict.",
  "recommended_partners": [
    {{"name": "Institution", "product": "Produit", "amount": {realistic_max}, "rate": "X%", "reason": "Pourquoi ce partenaire et ce produit pour CE profil"}}
  ],
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
