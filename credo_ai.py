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
# DONNEES REELLES PARTENAIRES UEMOA
# ==============================================================
REAL_LENDERS = [
    {
        "name": "FUCEC-Togo",
        "slug": "fucec-togo",
        "type": "microfinance",
        "min_loan": 50000,
        "max_loan": 5000000,
        "min_score": 400,
        "max_rate": "12-18%",
        "sectors": ["commerce", "agriculture", "artisanat", "elevage", "service"],
        "requires_collateral": True,
        "requires_savings": True,
        "group_lending": True,
        "documents": ["piece_identite", "photo_boutique", "preuve_revenus"],
        "desc": "Reseau national, accessible dans toutes les prefectures du Togo",
    },
    {
        "name": "WAGES Togo",
        "slug": "wages",
        "type": "microfinance",
        "min_loan": 30000,
        "max_loan": 3000000,
        "min_score": 350,
        "max_rate": "10-15%",
        "sectors": ["commerce", "agriculture", "artisanat"],
        "requires_collateral": False,
        "requires_savings": True,
        "group_lending": True,
        "documents": ["piece_identite", "preuve_revenus", "photo_activite"],
        "desc": "Microfinance specialisee femmes, groupe de 3 minimum",
    },
    {
        "name": "Orange Money Credit",
        "slug": "orange-money",
        "type": "fintech",
        "min_loan": 10000,
        "max_loan": 500000,
        "min_score": 200,
        "max_rate": "5% par mois",
        "sectors": ["commerce", "service", "elevage"],
        "requires_collateral": False,
        "requires_savings": False,
        "group_lending": False,
        "documents": ["piece_identite", "numero_orange_money"],
        "desc": "Credit mobile, disponible en 24h, sans garantie",
    },
    {
        "name": "MTN MoMo Credit",
        "slug": "mtn-momo",
        "type": "fintech",
        "min_loan": 10000,
        "max_loan": 500000,
        "min_score": 200,
        "max_rate": "5% par mois",
        "sectors": ["commerce", "service", "agriculture"],
        "requires_collateral": False,
        "requires_savings": False,
        "group_lending": False,
        "documents": ["piece_identite", "numero_mtn"],
        "desc": "Credit mobile MoMo, accessible 7j/7",
    },
    {
        "name": "Ecobank Togo",
        "slug": "ecobank",
        "type": "banque",
        "min_loan": 500000,
        "max_loan": 50000000,
        "min_score": 600,
        "max_rate": "6-10%",
        "sectors": ["commerce", "service", "agriculture", "industrie"],
        "requires_collateral": True,
        "requires_savings": True,
        "group_lending": False,
        "documents": ["piece_identite", "patente", "plan_affaires", "garantie"],
        "desc": "Banque panafricaine, taux competitifs pour PME formelles",
    },
    {
        "name": "Cofina Togo",
        "slug": "cofina",
        "type": "microfinance",
        "min_loan": 30000,
        "max_loan": 3000000,
        "min_score": 300,
        "max_rate": "12-18%",
        "sectors": ["commerce", "agriculture", "artisanat", "elevage"],
        "requires_collateral": True,
        "requires_savings": True,
        "group_lending": False,
        "documents": ["piece_identite", "preuve_revenus", "garantie"],
        "desc": "Microfinance nationale, agences dans 5 villes",
    },
    {
        "name": "BAOBAB Togo",
        "slug": "baobab",
        "type": "microfinance",
        "min_loan": 50000,
        "max_loan": 5000000,
        "min_score": 350,
        "max_rate": "10-16%",
        "sectors": ["commerce", "agriculture", "service", "elevage"],
        "requires_collateral": True,
        "requires_savings": True,
        "group_lending": False,
        "documents": ["piece_identite", "preuve_revenus", "photo_activite"],
        "desc": "Groupe panafricain, present dans 8 pays UEMOA",
    },
]


def log_groq_error(context: str, error: any):
    print(f"[CREDO GROQ ERROR] {context}: {error}")


def generate_code() -> str:
    chars = string.ascii_uppercase + string.digits
    suffix = ''.join(secrets.choice(chars) for _ in range(5))
    return f"CREDO-{suffix}"


def match_lenders(description: str, monthly_revenue: int = 0, amount_wanted: int = 0) -> list:
    """Trouve les partenaires pertinents selon le profil"""
    desc_lower = description.lower()
    matches = []
    for l in REAL_LENDERS:
        score = 0
        # Matching secteur
        for s in l["sectors"]:
            if s in desc_lower:
                score += 2
        # Matching montant
        if amount_wanted > 0:
            if l["min_loan"] <= amount_wanted <= l["max_loan"]:
                score += 3
            elif amount_wanted < l["min_loan"]:
                score -= 1
        # Matching revenu (approximatif)
        if monthly_revenue > 0 and l["min_score"] > 200:
            if monthly_revenue >= l["min_loan"] * 0.3:
                score += 1
        if score > 0:
            matches.append((score, l))
    matches.sort(key=lambda x: -x[0])
    return [l for _, l in matches[:3]]


def build_scoring_prompt(answers: list[dict], lenders_context: list[dict]) -> str:
    """Prompt scoring avec contexte des vrais partenaires"""
    qa_text = "\n".join(f"- {a.get('q', '')}: {a.get('a', '')}" for a in answers)

    lenders_text = "\n".join(
        f"- {l['name']}: pret {l['min_loan']}-{l['max_loan']} FCFA, "
        f"taux {l['max_rate']}, secteurs: {', '.join(l['sectors'])}. "
        f"Documents requis: {', '.join(l['documents'])}. {l['desc']}"
        for l in lenders_context
    )

    return f"""Tu es un analyste de credit pour le marche informel en Afrique de l'Ouest (UEMOA).
Evalue le profil suivant et retourne UNIQUEMENT un JSON valide.

Profil emprunteur:
{qa_text}

Partenaires disponibles correspondant au profil:
{lenders_text}

Instructions:
- Score sur 1000 (0=risque max, 1000=risque min)
- Adapte le scoring au marche informel: pas de fiche de paie = normal
- Un revenu stable meme informel est un bon signal
- L'epargne reguliere compense l'absence de garantie formelle
- Choisis LES 2 MEILLEURS partenaires de la liste ci-dessus
- Les documents demandes doivent correspondre aux documents requis par les partenaires selectionnes
- Le montant propose doit etre realiste pour le marche UEMOA

Retourne ce JSON (sans markdown, sans commentaires):
{{
  "score": 650,
  "risk": "Faible",
  "max_amount": 500000,
  "currency": "FCFA",
  "recommended_partners": [
    {{"name": "FUCEC-Togo", "amount": 500000, "rate": "12-18%", "reason": "Pourquoi ce partenaire correspond"}}
  ],
  "missing_documents": ["piece_identite", "preuve_revenus"],
  "improvement_tips": ["Conseil 1", "Conseil 2"],
  "analysis": "Analyse courte du profil (2-3 phrases)",
  "confidence": 0.85
}}"""


def score_from_answers(answers: list[dict]) -> dict:
    description = ""
    amount_wanted = 0
    revenue = 0
    for a in answers:
        txt = f"{a.get('q', '')} {a.get('a', '')}".lower()
        if "decris" in a.get('q', '').lower() or "description" in a.get('q', '').lower():
            description = a.get('a', '')
        nums = re.findall(r'\d+', a.get('a', ''))
        if nums:
            val = int(nums[0])
            if "montant" in a.get('q', '').lower() or "souhaites" in a.get('q', '').lower():
                amount_wanted = max(amount_wanted, val)
            if "revenu" in a.get('q', '').lower():
                revenue = max(revenue, val)

    lenders = match_lenders(description, revenue, amount_wanted)
    if not lenders:
        lenders = REAL_LENDERS[:3]

    prompt = build_scoring_prompt(answers, lenders)

    try:
        resp = client.chat.completions.create(
            model=SCORE_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=1024,
        )
        content = resp.choices[0].message.content
        data = json.loads(content)
        data["model"] = SCORE_MODEL
        data["tokens_used"] = getattr(resp.usage, "total_tokens", 0)
        log_groq_error("score_ok", f"tokens: {data['tokens_used']}")
        return data
    except Exception as e:
        log_groq_error("score_fallback", str(e))
        return _fallback_score(answers, lenders)


def _fallback_score(answers: list[dict], lenders: list[dict]) -> dict:
    score = 450
    max_amt = 200000
    partners = []

    for a in answers:
        r = (a.get("a") or "").lower()
        if "commerce" in r:
            score += 30
        if "agriculture" in r:
            score += 20
        if "eleveur" in r or "elevage" in r:
            score += 20
        nums = re.findall(r"\d+", r)
        if nums:
            val = int(nums[0])
            if "revenu" in (a.get("q") or "").lower():
                if val >= 500000:
                    score += 100
                    max_amt = max(max_amt, 2000000)
                elif val >= 200000:
                    score += 60
                    max_amt = max(max_amt, 1000000)
                elif val >= 100000:
                    score += 30
                    max_amt = max(max_amt, 500000)
            if "montant" in (a.get("q") or "").lower() or "souhaites" in (a.get("q") or "").lower():
                if val <= max_amt:
                    max_amt = val
        if "epargne" in r or "economie" in r:
            if "oui" in r:
                score += 60
        if "credit" in r or "pret" in r:
            if "jamais" in r or "non" in r:
                score -= 20
            elif "oui" in r:
                score += 50
        if "garantie" in r:
            score += 30

    score = max(0, min(1000, score))

    # Utilise les vrais partenaires
    for l in lenders[:3]:
        amount = min(l["max_loan"], max_amt)
        if amount >= l["min_loan"]:
            partners.append({
                "name": l["name"],
                "amount": amount,
                "rate": l["max_rate"],
                "reason": l["desc"][:80],
            })

    if not partners:
        partners = [{
            "name": lenders[0]["name"],
            "amount": lenders[0]["max_loan"],
            "rate": lenders[0]["max_rate"],
            "reason": "Partenaire recommande pour ce profil",
        }]

    docs = list(set(d for l in lenders[:2] for d in l["documents"]))

    tips = []
    if score < 400:
        tips.append("Augmente ton epargne reguliere pour renforcer ton dossier")
    if score < 600:
        tips.append("Reviens avec 3 mois de transactions mobile money")
    tips.append("Presente des photos de ton activite pour appuyer ton dossier" if any("photo" in d for d in docs) else "Prepare ta piece d'identite et tes justificatifs")

    return {
        "score": score,
        "risk": "Faible" if score > 650 else "Moyen" if score > 400 else "Eleve",
        "max_amount": max_amt,
        "currency": "FCFA",
        "recommended_partners": partners,
        "missing_documents": list(set(docs)),
        "improvement_tips": tips,
        "analysis": "Profil analyse avec nos criteres standards.",
        "confidence": 0.6,
        "model": "fallback",
        "tokens_used": 0,
    }


def build_chat_prompt(answers: list[dict]) -> str:
    """Question de suivi intelligente basee sur le contexte"""
    if not answers:
        return "Bonjour, je suis Credo. Decris-moi en quelques phrases le projet ou le besoin pour lequel tu as besoin d'un pret : quel secteur, combien, pour quoi faire ?"

    qa_text = "\n".join(f"- {a.get('q', '')}: {a.get('a', '')}" for a in answers)

    prompt = f"""Tu es un conseiller credit pour le marche africain. Pose UNE seule question breve en francais.

Le client a deja repondu:
{qa_text}

Analyse ce qui manque. La premiere question etait ouverte. Choisis LE sujet le plus critique:
- REVENUS: combien gagne-t-il par mois ?
- ACTIVITE: depuis combien de temps ?
- MONTANT: combien veut-il emprunter exactement ?
- EPARGNE: a-t-il une epargne ou compte mobile money ?
- CREDIT: a-t-il deja eu un credit ?
- GARANTIE: a-t-il des garanties ?

N'invente pas. Verifie si l'info existe deja dans ses reponses. Ne repose JAMAIS une question deja repondue.

Retourne UNIQUEMENT la question, en langage naturel. Maximum 20 mots."""
    try:
        resp = client.chat.completions.create(
            model=SCORE_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=100,
        )
        return resp.choices[0].message.content.strip().strip('"').strip("'")
    except Exception as e:
        log_groq_error("question_fallback", str(e))
        return _fallback_question(answers)


def _fallback_question(answers: list[dict]) -> str:
    """Determine la question non encore posee"""
    answered = set()
    for a in answers:
        q = (a.get("q") or "").lower()
        answered.add(q[:30])

    questions = [
        ("activite", "Quelle est ton activite principale ? (commerce, agriculture, service, artisanat)"),
        ("combien de temps", "Depuis combien de temps exerces-tu cette activite ?"),
        ("revenu", "Quel est ton revenu mensuel moyen approximatif ?"),
        ("montant", "Quel montant souhaites-tu emprunter ?"),
        ("epargne", "As-tu une epargne ou un compte mobile money actif ?"),
        ("credit", "As-tu deja eu un credit auparavant ?"),
        ("destination", "Quelle est la destination du pret ? (investissement, besoin perso, stock)"),
        ("garanties", "As-tu des garanties a proposer ? (boutique, terrain, vehicule)"),
    ]
    for key, q in questions:
        if not any(key in a for a in answered):
            return q
    return "Souhaites-tu ajouter d'autres informations utiles pour ton dossier ?"


def extract_document_fields(image_url: str, doc_type: str) -> dict:
    prompts = {
        "id_card": "Extrais de cette piece d'identite en JSON: nom, prenom, date_naissance, numero_piece, date_expiration, sexe",
        "bank_statement": "Extrais de ce releve bancaire en JSON: institution, solde_actuel, periode_debut, periode_fin, transactions_entrantes_montant, transactions_sortantes_montant",
        "business_license": "Extrais de ce registre de commerce en JSON: nom_entreprise, numero_rcm, date_creation, siege_social, activite",
        "selfie": "Verifie si c'est une photo de visage. Retourne JSON: detection_visage (bool), qualite (bonne/moyenne/mauvaise)",
        "receipt": "Extrais de ce recu/facture en JSON: montant, date, fournisseur, description",
        "proof_of_address": "Extrais en JSON: nom, adresse_complete, type_facture (eau/electricite/telephone/loyer), date",
        "business_photo": "Decris cette photo en JSON: type_commerce (boutique/atelier/restaurant/etal), estimation_taille (petite/moyenne/grande), etat_local (bon/moyen/mauvais)",
        "photo_activite": "Decris cette photo en JSON: type_activite, equipement_visible, etat_materiel, estimation_professionnalisme (faible/moyen/eleve)",
    }
    prompt = prompts.get(doc_type, f"Extrais les informations de ce document en JSON. Type: {doc_type}")
    try:
        resp = client.chat.completions.create(
            model=VISION_MODEL,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            }],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=1024,
        )
        content = resp.choices[0].message.content
        return json.loads(content)
    except Exception as e:
        log_groq_error("vision", str(e))
        return {"error": str(e), "doc_type": doc_type}
