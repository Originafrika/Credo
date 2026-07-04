import json, os, sys
import psycopg2

DSN = os.environ.get("NEON_DSN") or sys.argv[1] if len(sys.argv) > 1 else None
if not DSN:
    print("Pass DSN as env NEON_DSN or first argument")
    sys.exit(1)

conn = psycopg2.connect(DSN)
cur = conn.cursor()

mfi_data = [
    ('FUCEC-Togo', 'microfinance', 50000, 5000000, 400, '12-18%', True, ['commerce','agriculture','artisanat','elevage','service'], ['TG'], ['piece_identite','preuve_revenus'], 'Reseau national, agences partout au Togo'),
    ('WAGES Togo', 'microfinance', 30000, 3000000, 350, '10-15%', False, ['commerce','agriculture','artisanat'], ['TG'], ['piece_identite','preuve_revenus'], 'Microfinance specialisee femmes, taux reduits'),
    ('Cofina Togo', 'microfinance', 30000, 3000000, 300, '12-18%', True, ['commerce','agriculture','artisanat','elevage'], ['TG'], ['piece_identite','preuve_revenus','garantie'], 'Microfinance nationale'),
    ('BAOBAB Togo', 'microfinance', 50000, 5000000, 350, '10-16%', True, ['commerce','agriculture','elevage'], ['TG'], ['piece_identite','preuve_revenus'], 'Groupe panafricain, 8 pays'),
]
for d in mfi_data:
    cur.execute(
        "INSERT INTO partners (name, type, min_amount, max_amount, min_score, rate, collateral_required, sectors, countries, docs, description) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        d
    )

country_name = {
    'BJ': 'Benin', 'BF': 'Burkina Faso', 'CI': "Cote d'Ivoire",
    'GW': 'Guinea-Bissau', 'ML': 'Mali', 'NE': 'Niger',
    'SN': 'Senegal', 'TG': 'Togo'
}

bceao_path = os.path.join(os.path.dirname(__file__), 'bceao_extract.json')
with open(bceao_path) as f:
    bceao = json.load(f)

count_banks = 0
for b in bceao.get('banks', []):
    if b.get('base_rate') is None or float(b.get('base_rate', 0)) < 3:
        continue
    country = b.get('country', 'TG')
    base_rate = float(b.get('base_rate') or 0)
    max_rate = float(b.get('max_rate') or 0)
    sectors = ['commerce', 'agriculture', 'service', 'artisanat']
    docs = ['piece_identite', 'patente', 'plan_affaires', 'preuve_revenus']
    desc = "Banque agreee BCEAO - {}. Base rate: {}%".format(country_name.get(country, country), base_rate)
    cur.execute(
        "INSERT INTO partners (name, type, min_amount, max_amount, min_score, rate, collateral_required, sectors, countries, docs, description, base_rate, max_rate) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (b['name'][:100], 'banque', 100000, 50000000, 200, '{}%'.format(round(base_rate, 1)), True, sectors, [country], docs, desc, base_rate, max_rate)
    )
    count_banks += 1

conn.commit()

cur.execute("SELECT type, COUNT(*) FROM partners GROUP BY type ORDER BY type")
for t, c in cur.fetchall():
    print("  {}: {}".format(t, c))
print("Total partners seeded: {}".format(count_banks + len(mfi_data)))
conn.close()
