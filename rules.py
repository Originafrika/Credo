CRITERIA_POOL = [
    {"key": "montant_pret", "label": "Montant souhaité", "priority": 90},
    {"key": "revenu_mensuel", "label": "Revenu mensuel", "priority": 85},
    {"key": "secteur_activite", "label": "Secteur d'activité", "priority": 80},
    {"key": "profession", "label": "Profession", "priority": 40},
    {"key": "duree_remboursement", "label": "Durée de remboursement", "priority": 70},
    {"key": "garantie", "label": "Garantie", "priority": 65},
    {"key": "epargne", "label": "Épargne", "priority": 50},
    {"key": "credit_history", "label": "Historique de crédit", "priority": 60},
    {"key": "RC_ou_patente", "label": "RC ou patente", "priority": 30},
]

CONSUMER_CRITERIA = {"montant_pret", "revenu_mensuel", "secteur_activite", "duree_remboursement", "garantie", "epargne", "credit_history"}

CONSUMER_SECTORS = {"particulier", "consommation", "voyage", "tourisme", "sante", "education", "loisir", "habitat"}


def _detect_sector_from_profile(profile: dict) -> str:
    return (profile.get("secteur_activite") or "").lower()


def _is_consumer_sector(profile: dict) -> bool:
    return _detect_sector_from_profile(profile) in CONSUMER_SECTORS


def needed_criteria(profile: dict, partners: list[dict], products: list[dict]) -> list[str]:
    answered = {k for k, v in profile.items() if v is not None}
    is_consumer = _is_consumer_sector(profile)

    # Determine which criteria are discriminating based on partner data
    required = set()
    for p in partners:
        if p.get("min_amount") and "montant_pret" not in answered:
            required.add("montant_pret")
        if p.get("sectors") and "secteur_activite" not in answered:
            required.add("secteur_activite")

    for pr in products:
        if pr.get("collateral_required") and "garantie" not in answered:
            required.add("garantie")
        if pr.get("formal_required") and "profession" not in answered:
            required.add("profession")
        if pr.get("min_income") and "revenu_mensuel" not in answered:
            required.add("revenu_mensuel")

    # Always needed for any partner matching
    if not is_consumer:
        required.add("secteur_activite")
    required.add("montant_pret")
    required.add("revenu_mensuel")

    # Consumer loans: fewer criteria
    if is_consumer:
        pool = [c for c in CRITERIA_POOL if c["key"] in CONSUMER_CRITERIA]
    else:
        pool = CRITERIA_POOL[:]

    remaining = [c for c in pool if c["key"] not in answered and (c["key"] in required or c["key"] in CONSUMER_CRITERIA)]
    remaining.sort(key=lambda c: 100 if c["key"] in required else c["priority"], reverse=True)

    return [c["key"] for c in remaining]


def next_criterion(profile: dict, partners: list[dict], products: list[dict]) -> str | None:
    needed = needed_criteria(profile, partners, products)
    return needed[0] if needed else None


CRITERION_QUESTIONS = {
    "montant_pret": "Quel montant souhaites-tu emprunter ?",
    "revenu_mensuel": "Quel est ton revenu mensuel moyen ?",
    "secteur_activite": "Dans quel secteur exerces-tu ?",
    "profession": "Quelle est ta profession ?",
    "duree_remboursement": "Sur combien de mois souhaites-tu rembourser ?",
    "garantie": "As-tu une garantie à proposer (terrain, boutique, véhicule) ?",
    "epargne": "As-tu une épargne ?",
    "credit_history": "As-tu déjà eu un crédit ?",
    "RC_ou_patente": "As-tu un Registre de Commerce ou une Patente ?",
}


def default_question(criterion_key: str) -> str:
    return CRITERION_QUESTIONS.get(criterion_key, "Peux-tu en dire plus ?")


# ==============================================================
# SCORING ENGINE — Déterministe, auditable, testable
# Epic 3.1 — Remplace l'appel LLM dans score_from_answers()
# ==============================================================

def _safe_int(v, default=0) -> int:
    if v is None:
        return default
    try:
        return int(v)
    except (ValueError, TypeError):
        return default


def _safe_str(v, default="") -> str:
    if v is None:
        return default
    return str(v)


def _income_score(monthly_income: int) -> tuple[int, str]:
    if monthly_income >= 1000000:
        return 25, f"Revenu de {monthly_income:,} FCFA/mois — excellent"
    if monthly_income >= 500000:
        return 25, f"Revenu de {monthly_income:,} FCFA/mois — très bon"
    if monthly_income >= 300000:
        return 20, f"Revenu de {monthly_income:,} FCFA/mois — bon"
    if monthly_income >= 200000:
        return 15, f"Revenu de {monthly_income:,} FCFA/mois — moyen"
    if monthly_income >= 100000:
        return 10, f"Revenu de {monthly_income:,} FCFA/mois — faible"
    if monthly_income >= 50000:
        return 5, f"Revenu de {monthly_income:,} FCFA/mois — très faible"
    return 0, f"Revenu de {monthly_income:,} FCFA/mois — insuffisant"


def _collateral_score(has_collateral: bool) -> tuple[int, str]:
    if has_collateral:
        return 20, "Garantie disponible — sécurise le prêt"
    return 0, "Aucune garantie — risque plus élevé"


def _duration_score(duration_months: int) -> tuple[int, str]:
    if duration_months is None or duration_months <= 0:
        return 0, "Ancienneté non précisée"
    if duration_months >= 36:
        return 15, f"Activité établie depuis {duration_months} mois — stable"
    if duration_months >= 24:
        return 15, f"Activité établie depuis {duration_months} mois — bonne stabilité"
    if duration_months >= 12:
        return 12, f"Activité établie depuis {duration_months} mois — stable"
    if duration_months >= 6:
        return 8, f"Activité établie depuis {duration_months} mois — récente"
    return 4, f"Activité établie depuis {duration_months} mois — très récente"


def _credit_history_score(history: str) -> tuple[int, str]:
    h = _safe_str(history).lower()
    if h == "bon":
        return 15, "Bon historique de crédit — remboursements ponctuels"
    if h == "moyen":
        return 8, "Historique de crédit moyen"
    if h == "aucun":
        return 3, "Aucun historique de crédit"
    return 0, "Historique de crédit non précisé"


def _savings_score(has_savings: bool) -> tuple[int, str]:
    if has_savings:
        return 10, "Épargne disponible — bonne gestion financière"
    return 0, "Pas d'épargne déclarée"


def _business_reg_score(has_registration: bool) -> tuple[int, str]:
    if has_registration:
        return 5, "RC/Patente — activité formelle"
    return 0, "Pas de RC/Patente"


def _debt_ratio_score(amount_wanted: int, monthly_income: int) -> tuple[int, str]:
    if monthly_income <= 0:
        return 0, "Revenu non déclaré — ratio non calculable"
    ratio = (amount_wanted / monthly_income) * 100
    if ratio < 20:
        return 10, f"Ratio demande/revenu de {ratio:.0f}% — très raisonnable"
    if ratio < 30:
        return 10, f"Ratio demande/revenu de {ratio:.0f}% — raisonnable"
    if ratio < 50:
        return 6, f"Ratio demande/revenu de {ratio:.0f}% — modéré"
    if ratio < 80:
        return 3, f"Ratio demande/revenu de {ratio:.0f}% — élevé"
    return 0, f"Ratio demande/revenu de {ratio:.0f}% — trop élevé"


def _risk_level(score: int) -> str:
    if score >= 70:
        return "Faible"
    if score >= 40:
        return "Moyen"
    return "Élevé"


def compute_score(profile: dict) -> dict:
    income = _safe_int(profile.get("revenu_mensuel"))
    amount = _safe_int(profile.get("montant_pret"))
    collateral = bool(profile.get("garantie"))
    duration = _safe_int(profile.get("duree_activite") or profile.get("duree_remboursement"))
    credit_history = _safe_str(profile.get("credit_history"))
    has_savings = bool(profile.get("epargne"))
    has_biz_reg = bool(profile.get("RC_ou_patente"))

    factors = []
    total = 0

    inc_score, inc_note = _income_score(income)
    total += inc_score
    factors.append({"factor": "revenu", "score": inc_score, "max": 25, "note": inc_note})

    coll_score, coll_note = _collateral_score(collateral)
    total += coll_score
    factors.append({"factor": "garantie", "score": coll_score, "max": 20, "note": coll_note})

    dur_score, dur_note = _duration_score(duration)
    total += dur_score
    factors.append({"factor": "duree_activite", "score": dur_score, "max": 15, "note": dur_note})

    cred_score, cred_note = _credit_history_score(credit_history)
    total += cred_score
    factors.append({"factor": "credit_history", "score": cred_score, "max": 15, "note": cred_note})

    sav_score, sav_note = _savings_score(has_savings)
    total += sav_score
    factors.append({"factor": "epargne", "score": sav_score, "max": 10, "note": sav_note})

    biz_score, biz_note = _business_reg_score(has_biz_reg)
    total += biz_score
    factors.append({"factor": "RC_ou_patente", "score": biz_score, "max": 5, "note": biz_note})

    debt_score, debt_note = _debt_ratio_score(amount, income)
    total += debt_score
    factors.append({"factor": "ratio_dette", "score": debt_score, "max": 10, "note": debt_note})

    # Penalty for missing critical fields
    missing = []
    if not income:
        missing.append("revenu_mensuel")
    if not amount:
        missing.append("montant_pret")
    if missing:
        total = max(0, total - 10 * len(missing))

    score = min(total, 100)
    risk = _risk_level(score)

    return {
        "score": score,
        "risk": risk,
        "factors": factors,
        "max_amount": _compute_realistic_max_internal(income, collateral, amount),
        "missing_critical": missing,
    }


def _compute_realistic_max_internal(monthly_revenue: int, has_collateral: bool, amount_wanted: int) -> int:
    cap = 24 if has_collateral else 6
    realistic = monthly_revenue * cap
    if realistic < 50000:
        realistic = 50000
    capped = min(amount_wanted, realistic) if amount_wanted > 0 else realistic
    return capped
