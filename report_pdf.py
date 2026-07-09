import json
from io import BytesIO

from xhtml2pdf import pisa


def _render_simple(report: dict) -> str:
    p = report.get("profil", {})
    recs = report.get("top_recommendations", [])
    rec = recs[0] if recs else None
    score = report.get("score", 0)
    risk = report.get("risk", "N/A")

    rec_block = ""
    if rec:
        rec_block = f"""
        <div class="card">
            <h3>Recommandation</h3>
            <p><strong>{rec['name']}</strong> — {rec.get('type', '')}</p>
            <p>Taux estimé: {rec.get('rate', 'N/A')}</p>
            <p>Score de matching: {rec.get('match_percent', 0)}%</p>
        </div>"""

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
body {{ font-family: 'Helvetica', 'Arial', sans-serif; font-size: 12pt; color: #333; margin: 40px; }}
h1 {{ font-size: 22pt; color: #1a56db; margin-bottom: 5px; }}
h2 {{ font-size: 16pt; color: #374151; margin-top: 20px; }}
.card {{ background: #f3f4f6; padding: 15px; border-radius: 8px; margin: 10px 0; }}
.score {{ font-size: 36pt; font-weight: bold; color: #1a56db; }}
.score-label {{ font-size: 11pt; color: #6b7280; }}
.risk {{ display: inline-block; padding: 4px 12px; border-radius: 12px; font-weight: bold; }}
.risk-faible {{ background: #d1fae5; color: #065f46; }}
.risk-moyen {{ background: #fef3c7; color: #92400e; }}
.risk-eleve {{ background: #fee2e2; color: #991b1b; }}
.footer {{ margin-top: 30px; font-size: 9pt; color: #9ca3af; text-align: center; }}
table {{ width: 100%; border-collapse: collapse; margin: 10px 0; }}
th, td {{ padding: 8px; text-align: left; border-bottom: 1px solid #e5e7eb; }}
th {{ color: #6b7280; font-size: 10pt; }}
</style></head><body>
<h1>Credo — Rapport de Solvabilité</h1>
<p style="color:#6b7280;">Rapport Simple · Analyse personnalisée</p>

<div class="card" style="text-align:center;">
    <div class="score">{score}/100</div>
    <div class="score-label">Score de solvabilité</div>
    <div><span class="risk risk-{risk.lower()}">{risk}</span></div>
</div>

<h2>Votre profil</h2>
<table>
    <tr><th>Revenu mensuel</th><td>{p.get('monthly_income', 0):,} FCFA</td></tr>
    <tr><th>Montant demandé</th><td>{p.get('amount_wanted', 0):,} FCFA</td></tr>
    <tr><th>Montant réaliste max</th><td>{p.get('realistic_max', 0):,} FCFA</td></tr>
    <tr><th>Secteur</th><td>{p.get('sector', 'N/A')}</td></tr>
</table>

{rec_block}

<h2>Facteurs du score</h2>
<table>"""


def _render_complet(report: dict) -> str:
    p = report.get("profil", {})
    recs = report.get("top_recommendations", [])
    all_comps = report.get("all_comparisons", [])
    missing_docs = report.get("missing_documents", [])
    tips = report.get("improvement_tips", [])
    l2 = report.get("layer2", {})
    score = report.get("score", 0)
    risk = report.get("risk", "N/A")

    recs_html = ""
    for r in recs:
        recs_html += f"""
        <div class="card">
            <h3>{r['name']}</h3>
            <p>Type: {r.get('type', 'N/A')} · Score: {r.get('match_percent', 0)}% · Taux: {r.get('rate', 'N/A')}</p>
        </div>"""

    comps_html = ""
    for c in all_comps:
        status_color = {"eligible": "green", "partial": "orange", "not_eligible": "red"}.get(c.get("status", ""), "gray")
        comps_html += f"""
        <tr>
            <td>{c['name']}</td>
            <td>{c.get('rate', 'N/A')}</td>
            <td style="color:{status_color};">{c.get('status', 'N/A')}</td>
            <td>{c.get('match_percent', 0)}%</td>
        </tr>"""

    docs_html = ""
    if missing_docs:
        docs_html = "<h2>Documents manquants</h2><ul>" + "".join(f"<li>{d}</li>" for d in missing_docs) + "</ul>"

    tips_html = ""
    if tips:
        tips_html = "<h2>Conseils d'amélioration</h2><ul>" + "".join(f"<li>{t}</li>" for t in tips) + "</ul>"

    l2_html = ""
    if l2.get("summary"):
        l2_html = f"""
        <h2>Analyse comparative</h2>
        <div class="card"><p>{l2['summary']}</p></div>"""
    if l2.get("recommendations"):
        l2_html += "<h2>Comparaison détaillée</h2>"
        for rec in l2["recommendations"]:
            l2_html += f"""
            <div class="card">
                <p><strong>{rec.get('name', '')}</strong></p>
                <p>Mensualité estimée: {rec.get('estimated_monthly', 0):,} FCFA · Taux: {rec.get('estimated_rate', 0)}%</p>
                <p style="font-size:10pt;">{rec.get('why', '')}</p>
            </div>"""

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
body {{ font-family: 'Helvetica', 'Arial', sans-serif; font-size: 11pt; color: #333; margin: 40px; }}
h1 {{ font-size: 22pt; color: #1a56db; }}
h2 {{ font-size: 14pt; color: #374151; margin-top: 25px; border-bottom: 2px solid #e5e7eb; padding-bottom: 5px; }}
.card {{ background: #f9fafb; padding: 12px; border-radius: 6px; margin: 8px 0; border: 1px solid #e5e7eb; }}
.score {{ font-size: 36pt; font-weight: bold; color: #1a56db; }}
.risk {{ display: inline-block; padding: 4px 12px; border-radius: 12px; font-weight: bold; }}
.risk-faible {{ background: #d1fae5; color: #065f46; }}
.risk-moyen {{ background: #fef3c7; color: #92400e; }}
.risk-eleve {{ background: #fee2e2; color: #991b1b; }}
table {{ width: 100%; border-collapse: collapse; }}
th, td {{ padding: 6px 8px; text-align: left; border-bottom: 1px solid #e5e7eb; font-size: 10pt; }}
th {{ background: #f3f4f6; color: #374151; }}
.footer {{ margin-top: 30px; font-size: 8pt; color: #9ca3af; text-align: center; }}
</style></head><body>
<h1>Credo — Rapport de Solvabilité Complet</h1>
<p style="color:#6b7280;">Analyse multi-partenaires personnalisée</p>

<div class="card" style="text-align:center;">
    <div class="score">{score}/100</div>
    <div class="score-label">Score de solvabilité</div>
    <div><span class="risk risk-{risk.lower()}">{risk}</span></div>
</div>

<h2>Votre profil</h2>
<table>
    <tr><th>Revenu mensuel</th><td>{p.get('monthly_income', 0):,} FCFA</td></tr>
    <tr><th>Montant demandé</th><td>{p.get('amount_wanted', 0):,} FCFA</td></tr>
    <tr><th>Montant réaliste max</th><td>{p.get('realistic_max', 0):,} FCFA</td></tr>
    <tr><th>Secteur</th><td>{p.get('sector', 'N/A')}</td></tr>
    <tr><th>Garantie</th><td>{"Oui" if p.get('collateral') else "Non"}</td></tr>
    <tr><th>RC/Patente</th><td>{"Oui" if p.get('business_registration') else "Non"}</td></tr>
</table>

{l2_html}

<h2>Partenaires recommandés</h2>
{recs_html}

<h2>Comparatif complet ({len(all_comps)} institutions)</h2>
<table>
    <tr><th>Partenaire</th><th>Taux</th><th>Statut</th><th>Match</th></tr>
    {comps_html}
</table>

{docs_html}
{tips_html}

<div class="footer">
    Rapport généré par Credo — Origin SARL, Lomé, Togo<br>
    Ce rapport est une analyse indicative. Les décisions finales appartiennent aux institutions partenaires.
</div>
</body></html>"""


def generate_pdf(report: dict, package: str = "simple") -> bytes | None:
    try:
        if package == "simple":
            html = _render_simple(report)
        else:
            html = _render_complet(report)

        buf = BytesIO()
        pisa_status = pisa.CreatePDF(html, dest=buf)
        if pisa_status.err:
            return None
        return buf.getvalue()
    except Exception as e:
        print(f"[CREDO] PDF generation failed: {e}", flush=True)
        return None
