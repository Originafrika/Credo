#!/usr/bin/env python3
"""
BCEAO Conditions de Banque — Extracteur de donnees
Usage: python extract_bceao.py [--pdf path] [--output path]

Telecharge et extrait les taux bancaires du PDF BCEAO
Genere un fichier JSON compatible avec le seed de 001_schema.sql
"""

import json
import os
import re
import sys
import urllib.request
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional

try:
    import pdfplumber
except ImportError:
    print("pip install pdfplumber requests")
    sys.exit(1)


BCEAO_URL = (
    "https://ns2.bceao.int/sites/default/files/2026-04/"
    "Conditions-de-banque-Premier-semestre-2025.pdf"
)

COUNTRY_MAP = {
    "BENIN": "BJ", "BURKINA": "BF", "COTE D'IVOIRE": "CI",
    "COTE D IVOIRE": "CI", "CÔTE D'IVOIRE": "CI", "CÔTE D IVOIRE": "CI",
    "MALI": "ML", "NIGER": "NE", "SENEGAL": "SN", "TOGO": "TG",
    "GUINEE-BISSAU": "GW", "GUINEE BISSAU": "GW",
}

SECTOR_KEYWORDS = {
    "agriculture": ["agricole", "agriculture", "rural", "paysan", "culture", "elevage"],
    "commerce": ["commerce", "commercial", "distribution", "import", "export", "vente"],
    "service": ["service", "prestataire", "transport", "tourisme", "hotel", "restaurant"],
    "artisanat": ["artisan", "artisanat"],
    "industrie": ["industrie", "industriel", "manufacture", "transformation"],
}


@dataclass
class BankEntry:
    name: str
    country: str
    base_rate: Optional[float] = None
    max_rate: Optional[float] = None
    deposit_rate: Optional[float] = None


@dataclass
class ExtractedData:
    source: str = "BCEAO"
    period: str = "2025-S1"
    extracted_at: str = ""
    banks: list = field(default_factory=list)

    def to_dict(self):
        return {
            "source": self.source,
            "period": self.period,
            "extracted_at": self.extracted_at,
            "banks": [asdict(b) for b in self.banks],
        }


def download_pdf(url: str, path: str) -> str:
    if os.path.exists(path):
        print(f"  Fichier existe deja: {path}")
        return path
    print(f"  Telechargement: {url}")
    urllib.request.urlretrieve(url, path)
    print(f"  Sauvegarde: {path}")
    return path


def detect_country(text: str) -> Optional[str]:
    lines = text.split("\n")
    for line in lines:
        for name, code in COUNTRY_MAP.items():
            if name in line.upper():
                return code
    return None


def parse_rate(value: str) -> Optional[float]:
    value = value.strip().replace(",", ".").replace("%", "").replace(" ", "")
    if not value or value in ("-", "N/A", "n/a", "ND", "nd"):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def parse_pdf(pdf_path: str) -> list:
    """Parse le PDF BCEAO et extrait les entrees banques"""
    entries = []
    current_country = None
    lines_buffer = []

    print("  Parsing PDF...")
    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages):
            text = page.extract_text() or ""

            new_country = detect_country(text)
            if new_country:
                current_country = new_country

            # Cherche tableaux de taux
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    if not row or len(row) < 3:
                        continue
                    row_text = " ".join(str(c) for c in row if c).strip()
                    if not row_text:
                        continue

                    # Detecte une ligne banque: nom + taux
                    # Pattern: nom banque + taux base + taux max
                    cells = [str(c).strip() for c in row if c and str(c).strip()]
                    if len(cells) >= 3:
                        name = cells[0]
                        # Filtre les en-tetes et lignes non-banques
                        if any(kw in name.lower() for kw in [
                            "banque", "bank", "societe", "generale", "ecobank",
                            "orabank", "coris", "bAtlantic", "nsia", "boa",
                            "bicici", "sgb", "bhs", "brm", "uba", "bsic",
                            "citibank", "bdm", "bnd", "b gf", "bgfi",
                            "bridge", "sunu", "lba", "lbo", "cbao", "bimas",
                            "africa", "afrik", "bange", "ccei",
                        ]):
                            entry = BankEntry(
                                name=cells[0],
                                country=current_country or "TG",
                            )
                            if len(cells) >= 2:
                                entry.base_rate = parse_rate(cells[1])
                            if len(cells) >= 3:
                                entry.max_rate = parse_rate(cells[2])
                            if entry.base_rate or entry.max_rate:
                                entries.append(entry)

    return entries


def normalize_name(name: str) -> str:
    """Nettoie et standardise le nom de banque"""
    name = re.sub(r'\s+', ' ', name).strip()
    name = re.sub(r'[,.]$', '', name)
    return name


def generate_slug(name: str) -> str:
    slug = name.lower()
    slug = re.sub(r'[^a-z0-9]+', '-', slug)
    slug = slug.strip('-')
    return slug


def entries_to_lenders(entries: list) -> list:
    """Convertit les entrees extraites en format compatible schema"""
    seen = set()
    lenders = []

    for entry in entries:
        name = normalize_name(entry.name)
        slug = generate_slug(name)
        key = f"{slug}-{entry.country}"
        if key in seen:
            continue
        seen.add(key)

        lender = {
            "slug": slug,
            "name": name.title(),
            "type": "banque",
            "country": [entry.country],
            "min_loan": 100000,
            "max_loan": 50000000,
            "min_score": 500,
            "max_rate": entry.max_rate or 15.00,
            "target_sectors": ["commerce", "service"],
            "requires_collateral": True,
            "requires_business_reg": True,
            "max_duration_months": 36,
            "criteria": {
                "base_rate": entry.base_rate,
                "source": "BCEAO 2025-S1",
            },
        }
        lenders.append(lender)

    return lenders


def generate_seed_sql(lenders: list) -> str:
    """Genere le SQL INSERT pour ajouter aux donnees seeds"""
    lines = ["-- BCEAO Extract - Banques commerciales UEMOA"]
    lines.append("-- Genere automatiquement, a verifier avec le terrain\n")
    lines.append("INSERT INTO lenders (slug, name, type, country, min_loan, max_loan, min_score, max_rate, target_sectors, requires_collateral, requires_business_reg, max_duration_months, criteria) VALUES")

    values = []
    for l in lenders:
        countries = "{" + ",".join(l["country"]) + "}"
        sectors = "{" + ",".join(l["target_sectors"]) + "}"
        criteria = json.dumps(l["criteria"], ensure_ascii=False)
        rate = l["max_rate"] or "NULL"
        val = (
            f"('{l['slug']}', '{l['name'].replace(chr(39), chr(39)+chr(39))}', "
            f"'banque', '{countries}', {l['min_loan']}, {l['max_loan']}, "
            f"{l['min_score']}, {rate}, '{sectors}', "
            f"{'true' if l['requires_collateral'] else 'false'}, "
            f"{'true' if l['requires_business_reg'] else 'false'}, "
            f"{l['max_duration_months']}, '{criteria}')"
        )
        values.append(val)

    lines.append(",\n".join(values) + ";")
    return "\n".join(lines)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Extraction BCEAO Conditions de Banque")
    parser.add_argument("--pdf", default="/tmp/bceao_conditions.pdf", help="Chemin PDF")
    parser.add_argument("--output", default="", help="Dossier sortie")
    args = parser.parse_args()

    print("[BCEAO Extract]")
    pdf_path = download_pdf(BCEAO_URL, args.pdf)

    entries = parse_pdf(pdf_path)
    print(f"  {len(entries)} entrees bancaires extraites")

    # Nettoie les entrees suspectes (base_rate < 3.0 = probablement pas un taux)
    entries = [e for e in entries if (e.base_rate or 100) >= 3.0]
    print(f"  {len(entries)} apres filtrage (base_rate >= 3%)")

    lenders = entries_to_lenders(entries)
    print(f"  {len(lenders)} preteurs uniques generes")

    data = ExtractedData(extracted_at=datetime.now().isoformat())
    data.banks = entries

    output_dir = args.output or os.path.dirname(os.path.abspath(__file__))
    os.makedirs(output_dir, exist_ok=True)

    json_path = os.path.join(output_dir, "bceao_extract.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data.to_dict(), f, ensure_ascii=False, indent=2, default=str)
    print(f"  JSON: {json_path}")

    sql = generate_seed_sql(lenders)

    sql_path = os.path.join(output_dir, "bceao_seed_lenders.sql")
    with open(sql_path, "w", encoding="utf-8") as f:
        f.write(sql)
    print(f"  SQL: {sql_path}")
    print("  Termine.")

    # Stats
    countries = set()
    for l in lenders:
        countries.update(l["country"])
    print(f"\nPays couverts: {', '.join(sorted(countries))}")


if __name__ == "__main__":
    main()
