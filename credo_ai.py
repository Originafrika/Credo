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


def generate_code() -> str:
    """Genere un code de referral unique: CREDO-A7X3K"""
    chars = string.ascii_uppercase + string.digits
    suffix = ''.join(secrets.choice(chars) for _ in range(5))
    return f"CREDO-{suffix}"


def build_scoring_prompt(answers: list[dict]) -> str:
    """Construit le prompt pour le scoring IA a partir des reponses"""
    qa_text = "\n".join(f"- {a.get('q', 'Question')}: {a.get('a', '')}" for a in answers)
    return f"""Tu es un analyste de credit pour le marche informel en Afrique de l'Ouest (UEMOA).
Evalue le profil suivant et retourne UNIQUEMENT un JSON valide.

Profil emprunteur:
{qa_text}

Instructions:
- Score sur 1000 (0=risque max, 1000=risque min)
- Adapte le scoring au marche informel: pas de fiche de paie = normal
- Les secteurs comme commerce, agriculture, elevage sont courants
- Un revenu stable meme informel est un bon signal
- L'epargne reguliere compense l'absence de garantie formelle
- Le montant propose doit etre realiste pour le marche UEMOA

Retourne ce JSON (sans markdown, sans commentaires):
{{
  "score": 650,
  "risk": "Faible",
  "max_amount": 500000,
  "currency": "FCFA",
  "recommended_partners": [
    {{"name": "Nom Institution", "amount": 500000, "rate": "12%", "reason": "Pourquoi cette institution"}}
  ],
  "missing_documents": ["piece_identite", "justificatif_revenus"],
  "improvement_tips": ["Conseil 1", "Conseil 2"],
  "confidence": 0.85
}}"""


def score_from_answers(answers: list[dict]) -> dict:
    """Appelle Groq pour scorer le profil"""
    prompt = build_scoring_prompt(answers)
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
        return data
    except Exception as e:
        # Fallback: scoring basique si Groq echoue
        return _fallback_score(answers)


def _fallback_score(answers: list[dict]) -> dict:
    """Fallback local si Groq indisponible"""
    score = 500
    max_amt = 500000
    partners = [
        {"name": "FUCEC-Togo", "amount": 500000, "rate": "12%", "reason": "Microfinance accessible"},
        {"name": "WAGES", "amount": 300000, "rate": "10%", "reason": "Taux competitif"},
        {"name": "Orange Money Credit", "amount": 200000, "rate": "5%", "reason": "Sans garantie"},
    ]
    for a in answers:
        q = (a.get("q") or "").lower()
        r = (a.get("a") or "").lower()
        if "revenu" in q:
            nums = re.findall(r"\d+", r)
            if nums:
                rev = int(nums[0])
                if rev > 500000:
                    score += 150
                    max_amt = max(max_amt, 2000000)
                elif rev > 100000:
                    score += 80
        if "epargne" in r:
            score += 50
        if "credit" in r or "pret" in r:
            if "jamais" in r or "non" in r:
                score -= 30
            elif "oui" in r:
                score += 40
    score = max(0, min(1000, score))
    return {
        "score": score,
        "risk": "Faible" if score > 650 else "Moyen" if score > 400 else "Eleve",
        "max_amount": max_amt,
        "currency": "FCFA",
        "recommended_partners": partners,
        "missing_documents": ["piece_identite"],
        "improvement_tips": ["Augmente ton epargne pour un meilleur score"],
        "confidence": 0.6,
        "model": "fallback",
        "tokens_used": 0,
    }


def build_chat_prompt(answers: list[dict]) -> str:
    """Genere une question de suivi intelligente basee sur les reponses"""
    if not answers:
        return "Quelle est ton activite principale ? (ex: commerce, agriculture, service, artisanat)"

    qa_text = "\n".join(f"- {a.get('q', '')}: {a.get('a', '')}" for a in answers)
    prompt = f"""Tu es un assistant de scoring credit pour le marche africain.
Pose UNE question breve et naturelle pour completer le profil.

Questions deja posees et reponses:
{qa_text}

Ne pose qu'une seule question. Question en francais simple. 
Theme a explorer (choisis celui qui manque le plus):
1. Revenus mensuels
2. Anciennete dans l'activite
3. Epargne et habitudes financieres
4. Historique de credit
5. Garanties disponibles
6. Destination du pret (investissement, besoin perso, etc.)

Retourne UNIQUEMENT la question, pas de formatage."""
    try:
        resp = client.chat.completions.create(
            model=SCORE_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=128,
        )
        return resp.choices[0].message.content.strip().strip('"')
    except Exception:
        return _fallback_question(len(answers))


def _fallback_question(idx: int) -> str:
    FALLBACKS = [
        "Quelle est ton activite principale ?",
        "Depuis combien de temps exerces-tu ?",
        "Quel est ton revenu mensuel moyen ?",
        "Quel montant souhaites-tu emprunter ?",
        "As-tu deja eu un credit auparavant ?",
        "As-tu une epargne ou un compte mobile money ?",
        "Quelle est la destination du pret ?",
        "As-tu des garanties a proposer ?",
    ]
    return FALLBACKS[idx] if idx < len(FALLBACKS) else "Souhaites-tu ajouter autre chose ?"


def extract_document_fields(image_url: str, doc_type: str) -> dict:
    """Extraction de donnees depuis un document via vision"""
    prompts = {
        "id_card": "Extrais les informations de cette piece d'identite en JSON: nom, prenom, date_naissance, numero_piece, date_expiration",
        "bank_statement": "Extrais les informations de ce releve bancaire en JSON: institution, solde, periode, transactions",
        "business_license": "Extrais les informations de ce registre de commerce en JSON: nom_entreprise, numero, date_creation",
        "selfie": "Verifie si c'est une photo de visage. Retourne JSON: detection_visage (bool), qualite (bonne/moyenne/mauvaise)",
        "receipt": "Extrais les informations de ce recu/facture en JSON: montant, date, fournisseur, description",
        "proof_of_address": "Extrais les informations en JSON: nom, adresse, type_facture, date",
        "business_photo": "Decris cette photo de commerce en JSON: type_commerce, estimation_taille, etat_local",
    }
    prompt = prompts.get(doc_type, "Decris ce document en JSON avec les champs pertinents.")
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
        return {"error": str(e), "doc_type": doc_type}
