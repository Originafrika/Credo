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
    """LLM querie la DB au moment du scoring: partenaires + produits + regles metier."""
    if not NEON_DSN:
        return [], [], []
    try:
        conn = psycopg2.connect(NEON_DSN)
        cur = conn.cursor()

        # query partners
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

        # query products for matching partners
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

        # query relevant knowledge base rules
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
    """Extrait tous les nombres d'un texte (supporte 1.000.000, 1 000 000, 1000000)"""
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
    """Trouve le montant demande. Check description + questions reponses."""
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
    """Calcule un montant realiste base sur le revenu.
    Regle: sans collaterale max 6x revenu, avec collaterale max 24x."""
    cap = 24 if has_collateral else 6
    realistic = monthly_revenue * cap

    # Si la personne veut plus que le realistic, on plafonne
    if amount_wanted > 0 and amount_wanted > realistic:
        return realistic

    return min(amount_wanted, realistic) if amount_wanted > 0 else realistic


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
        if "garantie" in r and ("terrain" in r or "boutique" in r or "maison" in r or "vehicule" in r or "oui" in r):
            has_collateral = True

    realistic_max = _compute_realistic_max(monthly_income, has_collateral, amount_wanted)

    prompt = _build_groq_prompt(answers, monthly_income, amount_wanted, has_collateral, realistic_max)
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
    _log(f"Groq score OK: {data.get('score')}, tokens: {data['tokens_used']}")
    return data


def _build_groq_prompt(answers: list[dict], income: int, wanted: int, collateral: bool, realistic_max: int) -> str:
    qa = "\n".join(f"- {a.get('q', '')}: {a.get('a', '')}" for a in answers)

    # LLM query DB au moment du scoring
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
        f"- {p['name']} ({p['type']}): {p['min_amount']:,}-{p['max_amount']:,} FCFA, taux {p['rate']}"
        for p in partners
    ) if partners else "Aucun partenaire trouve dans la base."

    products_str = "\n".join(
        f"- {pr['product']} ({pr['partner']}): {pr['min_amount']:,}-{pr['max_amount']:,} FCFA, {pr['min_duration']}-{pr['max_duration']}mois, taux {pr['annual_rate']}%"
        for pr in products[:8]
    ) if products else ""

    rules_str = "\n".join(
        f"  [{r['category']}] {r['title']}: {r['content']}"
        for r in rules[:6]
    ) if rules else ""

    return f"""Tu es un analyste de credit pour le marche UEMOA. Evalue CE profil precis.

Profil:
{qa}

Revenu mensuel: {income} FCFA
Montant demande: {wanted} FCFA
Collateral: {"oui" if collateral else "non"}
Montant realiste max (calcule): {realistic_max} FCFA

--- PARTENAIRES DISPONIBLES (base de donnees) ---
{partners_str}

--- PRODUITS DE CREDIT ---
{products_str}

--- REGLES METIER ---
{rules_str}

Instructions:
- Si le montant demande est irrealiste, explique-le dans analysis
- Le marche informel est normal en Afrique, ce n'est pas un risque
- Choisis TOUJOURS les partenaires parmi la liste ci-dessus — ne pas en inventer
- Associe chaque partenaire recommande a un produit specifique de sa gamme
- Prefere les microfinances aux banques pour les petits montants (<1MF)

Retourne CE JSON:
{{
  "score": 450,
  "risk": "Eleve",
  "max_amount": 500000,
  "analysis": "2-3 phrases expliquant le verdict honnetement",
  "recommended_partners": [
    {{"name": "Institution", "product": "Nom produit", "amount": 300000, "rate": "12%", "reason": "Pourquoi ce partenaire et ce produit"}}
  ],
  "missing_documents": ["piece_identite"],
  "improvement_tips": ["Conseil 1"],
  "confidence": 0.85
}}"""





# ==============================================================
# CHAT / QUESTIONS
# ==============================================================

def build_first_question() -> str:
    return "Bonjour, je suis Credo. Decris-moi en quelques phrases ton projet ou le besoin pour lequel tu as besoin d'un pret : quel secteur, combien, pour quoi faire ?"


def build_next_question(answers: list[dict]) -> str:
    """Pose UNE question basee sur ce qui manque vraiment."""
    answered_topics = set()
    for a in answers:
        q = (a.get("q") or "").lower()[:15]
        r = (a.get("a") or "").lower()
        answered_topics.add(q)
        if "decris" in q:
            # Check what info the user already gave in description
            if any(w in r for w in ["million", "mf", "f", "franc", "fca"]):
                answered_topics.add("montant")
            if any(w in r for w in ["commerce", "agriculture", "service", "artisanat", "labo", "tech", "ia", "numerique"]):
                answered_topics.add("activite")
            if any(w in r for w in ["mois", "an", "depuis", "janvier", "2024", "2025", "2026"]):
                answered_topics.add("duree")

    # Build a prompt for Groq
    hist = "\n".join(f"- Q: {a.get('q', '')}\n  R: {a.get('a', '')}" for a in answers)

    prompt = f"""Tu es un conseiller credit qui pose UNE question a la fois. En francais, tutoie ("tu").

Le client a repondu:
{hist}

Choisis LE sujet le plus critique PARMI ceux-ci (ne pose pas de question deja repondue):
- ACTIVITE: si tu ne sais pas ce qu'il fait
- MONTANT: si tu ne sais pas combien il veut
- REVENU: si tu ne sais pas combien il gagne par mois
- DUREE: si tu ne sais pas depuis quand il exerce
- EPARGNE: si tu ne sais pas s'il epargne
- CREDIT: si tu ne sais pas s'il a deja eu un credit
- GARANTIE: si tu ne sais pas s'il a des garanties

Ne pose qu'une seule question. Maximum 12 mots. Naturel. En "tu"."""

    resp = client.chat.completions.create(
        model=SCORE_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        max_tokens=80,
    )
    q = resp.choices[0].message.content.strip().strip('"').strip("'")
    return q if q else "Peux-tu m'en dire plus ?"

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
