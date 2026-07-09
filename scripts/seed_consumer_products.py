"""Seed : ajoute secteurs conso + produits consommation à TOUS les partenaires.
Usage: python scripts/seed_consumer_products.py NEON_DSN

Ajoute 'particulier' et 'consommation' aux secteurs de TOUS les partenaires bancaires
(banque, microfinance), puis insère un produit consommation standard pour chacun.
"""
import sys
import psycopg2

DSN = sys.argv[1] if len(sys.argv) > 1 else None
if not DSN:
    print("Usage: python scripts/seed_consumer_products.py NEON_DSN")
    sys.exit(1)

conn = psycopg2.connect(DSN)
cur = conn.cursor()

# Also clean any duplicates first
cur.execute("SELECT name, COUNT(*) FROM partners GROUP BY name HAVING COUNT(*) > 1")
for name, cnt in cur.fetchall():
    cur.execute("SELECT id FROM partners WHERE name = %s ORDER BY id", (name,))
    ids = [r[0] for r in cur.fetchall()]
    for rid in ids[1:]:
        cur.execute("DELETE FROM products WHERE partner_id = %s", (rid,))
        cur.execute("DELETE FROM partners WHERE id = %s", (rid,))
conn.commit()

print("=== Phase 1: Ajout secteurs consommation ===")

# Add consumer sectors to ALL banks and MFIs
cur.execute(
    "UPDATE partners SET sectors = sectors || ARRAY['particulier','consommation'] "
    "WHERE type IN ('banque', 'microfinance') AND NOT (sectors @> ARRAY['particulier'])"
)
print(f"  Partenaires mis à jour: {cur.rowcount}")

# FUCEC gets extra specific sectors
cur.execute("UPDATE partners SET sectors = sectors || ARRAY['voyage','sante','education','habitat'] WHERE name LIKE '%FUCEC%' AND NOT (sectors @> ARRAY['voyage'])")
print(f"  FUCEC secteurs spécifiques ajoutés: {cur.rowcount}")

print("\n=== Phase 2: Insertion produits consommation ===")

# Banks: Pret Personnel
cur.execute("SELECT id, name FROM partners WHERE type = 'banque'")
banks = cur.fetchall()
for pid, pname in banks:
    cur.execute("SELECT id FROM products WHERE partner_id = %s AND name IN ('Pr\u00eat Personnel', 'Credit Standard')", (pid,))
    if cur.fetchone():
        continue
    cur.execute(
        "INSERT INTO products (partner_id, name, min_amount, max_amount, min_duration_months, max_duration_months, "
        "annual_rate, collateral_required, requirements, description) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (pid, "Pr\u00eat Personnel", 100000, 5000000, 6, 48, 12.0, False,
         ["piece_identite", "preuve_revenus", "contrat_travail"],
         "Pr\u00eat personnel sans garantie pour consommation, voyage, sant\u00e9, \u00e9ducation")
    )
print(f"  Produits banques: {len(banks)}")

# MFIs: Credit Particulier
cur.execute("SELECT id, name FROM partners WHERE type = 'microfinance'")
mfis = cur.fetchall()
for pid, pname in mfis:
    cur.execute("SELECT id FROM products WHERE partner_id = %s", (pid,))
    if cur.fetchone():
        continue
    cur.execute(
        "INSERT INTO products (partner_id, name, min_amount, max_amount, min_duration_months, max_duration_months, "
        "annual_rate, collateral_required, requirements, description) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (pid, "Cr\u00e9dit Particulier", 50000, 3000000, 3, 24, 15.0, False,
         ["piece_identite", "preuve_revenus"],
         "Cr\u00e9dit personnel pour besoins consommation, voyage, sant\u00e9, \u00e9ducation")
    )
print(f"  Produits microfinances: {len(mfis)}")

print("\n=== Phase 3: Entr\u00e9es knowledge_base ===")
kb_entries = [
    ('regle_score', 'Credit consommation particulier',
     'Pour un credit consommation (voyage, sante, education, personnel): les documents principaux sont piece_identite, preuve_revenus, contrat_travail. Pas besoin de patente ou plan_affaires.'),
    ('regle_score', 'Ratio credit consommation',
     'Pour un credit personnel sans garantie: le montant maximum est de 6x le revenu mensuel. La mensualite ne doit pas exceder 40% du revenu.'),
    ('partenaire', 'Produits consommation disponibles',
     'Les banques et microfinances du reseau proposent des prets personnels de 50K a 5M FCFA pour consommation, voyage, sante, education. Les fintechs proposent du credit mobile 5K-1M.'),
]
for cat, title, content in kb_entries:
    cur.execute("INSERT INTO knowledge_base (category, title, content) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                (cat, title, content))
print("  KB: 3 entr\u00e9es")

conn.commit()

cur.execute("SELECT type, COUNT(*) FROM partners GROUP BY type ORDER BY type")
print("\n=== R\u00e9sum\u00e9 ===")
for t, c in cur.fetchall():
    print(f"  {t}: {c}")
cur.execute("SELECT COUNT(*) FROM products")
print(f"Total produits: {cur.fetchone()[0]}")
conn.close()
print("\nTermin\u00e9.")
