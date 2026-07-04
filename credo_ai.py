import json
import os
import re
import secrets
import string
from datetime import datetime

from groq import Groq

client = Groq(api_key=os.environ.get("GROQ_API_KEY", ""))

SCORE_MODEL = "llama-3.3-70b-versatile"
VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

# ==============================================================
# BCEAO BANKS
# ==============================================================
_BCEAO_DATA = None

def _load_bceao():
    global _BCEAO_DATA
    if _BCEAO_DATA is not None:
        return
    path = os.path.join(os.path.dirname(__file__), "scripts", "bceao_extract.json")
    try:
        with open(path, "r") as f:
            _BCEAO_DATA = json.load(f)
    except:
        _BCEAO_DATA = {"banks": []}

# ==============================================================
# MFI LENDERS (data-proven partners)
# ==============================================================
MFI_LENDERS = [
    {"name": "FUCEC-Togo", "type": "microfinance", "min": 50000, "max": 5000000, "min_score": 400, "rate": "12-18%", "collateral": True, "sectors": ["commerce", "agriculture", "artisanat", "elevage", "service"], "docs": ["piece_identite", "preuve_revenus"], "desc": "Reseau national, agences partout au Togo"},
    {"name": "WAGES Togo", "type": "microfinance", "min": 30000, "max": 3000000, "min_score": 350, "rate": "10-15%", "collateral": False, "sectors": ["commerce", "agriculture", "artisanat"], "docs": ["piece_identite", "preuve_revenus"], "desc": "Microfinance specialisee femmes, taux reduits"},
    {"name": "Cofina Togo", "type": "microfinance", "min": 30000, "max": 3000000, "min_score": 300, "rate": "12-18%", "collateral": True, "sectors": ["commerce", "agriculture", "artisanat", "elevage"], "docs": ["piece_identite", "preuve_revenus", "garantie"], "desc": "Microfinance nationale"},
    {"name": "BAOBAB Togo", "type": "microfinance", "min": 50000, "max": 5000000, "min_score": 350, "rate": "10-16%", "collateral": True, "sectors": ["commerce", "agriculture", "elevage"], "docs": ["piece_identite", "preuve_revenus"], "desc": "Groupe panafricain, 8 pays"},
]

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

    # Try Groq first
    prompt = _build_groq_prompt(answers, monthly_income, amount_wanted, has_collateral, realistic_max)
    try:
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
    except Exception as e:
        _log(f"Groq failed ({e}), using fallback")
        return _fallback_score(answers, monthly_income, amount_wanted, has_collateral, realistic_max)


def _build_groq_prompt(answers: list[dict], income: int, wanted: int, collateral: bool, realistic_max: int) -> str:
    qa = "\n".join(f"- {a.get('q', '')}: {a.get('a', '')}" for a in answers)
    return f"""Tu es un analyste de credit pour le marche UEMOA. Evalue CE profil precis.

Profil:
{qa}

Revenu mensuel: {income} FCFA
Montant demande: {wanted} FCFA
Collateral: {"oui" if collateral else "non"}
Montant realiste max (calcule): {realistic_max} FCFA

Tu es STRICT:
- Jamais de pret > 6x le revenu mensuel sans collaterale
- Jamais de pret > 24x avec collaterale solide
- Si le montant demande est irrealiste, explique-le dans analysis
- Le marche informel est normal en Afrique, ce n'est pas un risque
- 90M pour un labo IA avec 40k/mois = IRREALISTE, expliquer pourquoi
- Un score bas avec explication honnete vaut mieux qu'un faux espoir

Retourne CE JSON:
{{
  "score": 450,
  "risk": "Eleve",
  "max_amount": 500000,
  "analysis": "2-3 phrases expliquant le verdict honnetement",
  "recommended_partners": [
    {{"name": "Institution", "amount": 300000, "rate": "12%", "reason": "Pourquoi ce partenaire"}}
  ],
  "missing_documents": ["piece_identite"],
  "improvement_tips": ["Conseil 1"],
  "confidence": 0.85
}}"""


def _fallback_score(answers: list[dict], income: int, wanted: int, collateral: bool, realistic_max: int) -> dict:
    """Fallback intelligent avec regles financieres reelles"""
    score = 500
    tips = []
    missing = ["piece_identite"]
    description = ""
    sector = ""

    for a in answers:
        r = (a.get("a") or "").lower()
        q = (a.get("q") or "").lower()
        if "decris" in q[:8]:
            description = r
        if "activite" in q or "fais" in q:
            sector = r

    # Determine sector from description
    combined = (description + " " + sector).lower()
    if any(w in combined for w in ["commerce", "vente", "boutique", "magasin"]):
        sector_key = "commerce"
        score += 40
    elif any(w in combined for w in ["agriculture", "ferme", "champ", "culture", "elevage"]):
        sector_key = "agriculture"
        score += 30
    elif any(w in combined for w in ["service", "transport", "restaurant", "hotel"]):
        sector_key = "service"
        score += 20
    elif any(w in combined for w in ["artisan", "atelier", "couture", "menuiserie"]):
        sector_key = "artisanat"
        score += 30
    else:
        sector_key = "commerce"

    # Revenue scoring
    if income > 0:
        if income >= 500000:
            score += 120
        elif income >= 200000:
            score += 80
        elif income >= 100000:
            score += 50
        elif income >= 50000:
            score += 20
        else:
            score += 5  # low income but active

    # Amount requested vs realistic
    amount_wanted = wanted
    requested_amount = amount_wanted if amount_wanted > 0 else realistic_max

    ratio = requested_amount / max(income, 1)
    if ratio > 100:
        score -= 150
        tips.append("Le montant demande est tres eleve par rapport a tes revenus. Commence par un pret plus modeste pour construire un historique.")
    elif ratio > 50:
        score -= 80
        tips.append("Le montant depasse ta capacite de remboursement actuelle. Un pret progressif est recommande.")
    elif ratio > 12:
        score -= 30
        tips.append("Le montant demande est eleve. Pense a apporter des garanties.")

    # Final amount
    final_amount = realistic_max
    if final_amount <= 0:
        final_amount = min(max(income * 3, 100000), 1000000)

    # Collateral
    if collateral:
        score += 60
        final_amount = min(final_amount, income * 24)
    else:
        final_amount = min(final_amount, income * 6)

    # Savings
    has_savings = any("epargne" in (a.get("q") or "").lower() and "oui" in (a.get("a") or "").lower() for a in answers)
    mobile_money = any("mobile money" in (a.get("a") or "").lower() or "momo" in (a.get("a") or "").lower() for a in answers)
    if has_savings:
        score += 50
        missing.append("preuve_epargne")
    if mobile_money and not has_savings:
        missing.append("releve_mobile_money")
        score -= 10

    # Credit history
    has_credit = any("credit" in (a.get("q") or "").lower() and "oui" in (a.get("a") or "").lower() for a in answers)
    if has_credit:
        score += 50
        missing.append("historique_credit")
    else:
        score -= 20

    # Business duration
    for a in answers:
        r = (a.get("a") or "").lower()
        if "mois" in r or "an" in r or "ans" in r or "janvier" in r or "depuis" in r:
            nums = _extract_numbers(r)
            if nums and nums[0] >= 12:
                score += 40
            elif nums and nums[0] >= 6:
                score += 20
                tips.append("Ton activite commence a etre stable. Continue a developper ton historique.")

    age_analysis = ""
    if income < 100000 and score < 500:
        age_analysis = "Le profil est en phase de demarrage. Les revenus actuels ne permettent pas un pret important."
    elif score >= 650:
        age_analysis = "Profil solide avec des revenus stables et une bonne gestion financiere."
    else:
        age_analysis = "Profil en construction. Un pret modeste et un accompagnement permettraient de monter en capacite."

    # Not enough revenue
    if income < 100000 and amount_wanted > 1000000:
        age_analysis += " Le montant demande depasse largement la capacite actuelle. Recommandation: commencer par un micro-credit pour batir un historique."
        final_amount = min(final_amount, 500000)

    # Cap final amount
    if final_amount < 10000:
        final_amount = 100000

    score = max(0, min(1000, score))
    risk = "Faible" if score > 650 else "Moyen" if score > 400 else "Eleve"

    # Match real partners
    partners = _match_by_amount(final_amount, sector_key)
    for p in partners:
        if p["docs"]:
            for d in p["docs"]:
                if d not in missing:
                    missing.append(d)

    if not tips:
        if score < 400:
            tips.append("Augmente tes revenus et cree une epargne reguliere avant de demander un pret")
        elif score < 650:
            tips.append("Construis un historique de credit avec des petits prets rembourses a temps")
        elif has_credit:
            tips.append("Continue a maintenir un bon historique de credit")
        tips.append("Prepare un plan d'utilisation des fonds pour rassurer le partenaire")

    return {
        "score": score,
        "risk": risk,
        "max_amount": final_amount,
        "currency": "FCFA",
        "analysis": age_analysis,
        "recommended_partners": partners,
        "missing_documents": list(set(missing)),
        "improvement_tips": tips[:3],
        "confidence": 0.65,
        "model": "fallback",
        "tokens_used": 0,
    }


def _match_by_amount(amount: int, sector: str) -> list:
    """Trouve les vrais partenaires qui pretent ce montant."""
    _load_bceao()
    candidates = []

    # Add BCEAO banks
    all_banks = _get_bceao_banks()
    for b in all_banks:
        if amount <= 10000000:
            rate = b.get("max_rate_pct", 15)
            candidates.append({
                "name": b["name"].title()[:30],
                "amount": amount,
                "rate": f"{rate}%",
                "reason": "Banque agreee BCEAO, taux competitif",
                "docs": ["piece_identite", "patente", "plan_affaires"],
                "min": 100000,
                "max": 50000000,
            })

    # Add MFIs
    for m in MFI_LENDERS:
        if m["min"] <= amount <= m["max"]:
            candidates.append({
                "name": m["name"],
                "amount": amount,
                "rate": m["rate"],
                "reason": m["desc"],
                "docs": m["docs"],
                "min": m["min"],
                "max": m["max"],
            })

    if not candidates:
        candidates.append({
            "name": "FUCEC-Togo",
            "amount": max(amount, 50000),
            "rate": "12-18%",
            "reason": "Reseau national accessible",
            "docs": ["piece_identite", "preuve_revenus"],
            "min": 50000,
            "max": 5000000,
        })

    # Sort by closest match to amount
    candidates.sort(key=lambda x: abs(x["min"] - amount))
    result = []
    seen = set()
    for c in candidates:
        if c["name"] not in seen:
            seen.add(c["name"])
            result.append(c)
        if len(result) >= 3:
            break

    return result


def _get_bceao_banks(country: str = "TG") -> list:
    _load_bceao()
    result = []
    for b in _BCEAO_DATA.get("banks", []):
        if b.get("country") == country and (b.get("base_rate") or 0) >= 3:
            result.append({
                "name": b["name"],
                "base_rate": b["base_rate"],
                "max_rate_pct": b["max_rate"],
            })
    return result


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

    try:
        resp = client.chat.completions.create(
            model=SCORE_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=80,
        )
        q = resp.choices[0].message.content.strip().strip('"').strip("'")
        if q:
            return q
    except:
        pass

    return _fallback_question(answered_topics)


def _fallback_question(answered: set) -> str:
    needed = [
        ("activite", "Quelle est ton activite principale ?"),
        ("duree", "Depuis combien de temps exerces-tu ?"),
        ("revenu", "Combien gagnes-tu par mois environ ?"),
        ("montant", "Combien souhaites-tu emprunter exactement ?"),
        ("epargne", "As-tu une epargne ou un compte mobile money ?"),
        ("credit", "As-tu deja eu un credit auparavant ?"),
        ("garantie", "As-tu des garanties a proposer ? (terrain, boutique, vehicule)"),
    ]
    for key, q in needed:
        if not any(k in str(answered) for k in [key]):
            return q
    return "Souhaites-tu ajouter d'autres informations ?"


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
