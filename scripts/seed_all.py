"""Seed complet pour Credo : partners + products + knowledge_base.
Usage: python scripts/seed_all.py "postgresql://..."
"""
import sys, json
import psycopg2

DSN = sys.argv[1] if len(sys.argv) > 1 else None
if not DSN:
    print("Usage: python scripts/seed_all.py NEON_DSN")
    sys.exit(1)

conn = psycopg2.connect(DSN)
cur = conn.cursor()

# -- partners (institutions financieres)
partners = [
    # Microfinances
    ('FUCEC-Togo', 'microfinance', 50000, 5000000, 400, '12-18%', ['commerce','agriculture','artisanat','elevage','service'], ['TG'], ['piece_identite','preuve_revenus'], 'Reseau national, agences partout au Togo', 12.0, 18.0),
    ('WAGES Togo', 'microfinance', 30000, 3000000, 350, '10-15%', ['commerce','agriculture','artisanat'], ['TG'], ['piece_identite','preuve_revenus'], 'Microfinance specialisee femmes, taux reduits', 10.0, 15.0),
    ('Cofina Togo', 'microfinance', 30000, 3000000, 300, '12-18%', ['commerce','agriculture','artisanat','elevage'], ['TG'], ['piece_identite','preuve_revenus','garantie'], 'Microfinance nationale', 12.0, 18.0),
    ('BAOBAB Togo', 'microfinance', 50000, 5000000, 350, '10-16%', ['commerce','agriculture','elevage'], ['TG'], ['piece_identite','preuve_revenus'], 'Groupe panafricain, 8 pays', 10.0, 16.0),
    ('Advans CI', 'microfinance', 25000, 2000000, 350, '15-20%', ['commerce','artisanat','service'], ['CI'], ['piece_identite','preuve_revenus'], 'Microfinance presente en CI', 15.0, 20.0),
    ('MECREF Togo', 'microfinance', 20000, 1000000, 300, '12-18%', ['commerce','agriculture','artisanat'], ['TG'], ['piece_identite','preuve_revenus'], 'Microfinance Togolaise', 12.0, 18.0),
    ("Fin'Elle Togo", 'microfinance', 25000, 2000000, 300, '10-14%', ['commerce','artisanat'], ['TG'], ['piece_identite','preuve_revenus'], 'Microfinance dediee aux femmes', 10.0, 14.0),
    # Banques Togo
    ('Ecobank Togo', 'banque', 100000, 50000000, 500, '8-15%', ['commerce','service','agriculture','industrie'], ['TG'], ['piece_identite','patente','plan_affaires','preuve_revenus'], 'Banque panafricaine, reseau UEMOA', 8.0, 15.0),
    ('Orabank Togo', 'banque', 100000, 50000000, 500, '9-15%', ['commerce','service','agriculture'], ['TG'], ['piece_identite','patente','preuve_revenus'], 'Banque regionale UEMOA', 9.0, 15.0),
    ('Societe Generale Togo', 'banque', 100000, 50000000, 500, '9-13%', ['commerce','service','agriculture'], ['TG'], ['piece_identite','patente','plan_affaires'], 'Banque internationale', 9.0, 13.0),
    ('BOA Togo', 'banque', 100000, 50000000, 500, '9-13%', ['commerce','service','agriculture'], ['TG'], ['piece_identite','patente','preuve_revenus'], 'Bank of Africa - Groupe panafricain', 9.0, 13.0),
    ('Coris Bank Togo', 'banque', 100000, 50000000, 500, '8-14%', ['commerce','service','agriculture'], ['TG'], ['piece_identite','patente','preuve_revenus'], 'Banque regionale', 8.0, 14.0),
    ('NSIA Banque Togo', 'banque', 100000, 50000000, 500, '9-14%', ['commerce','service','agriculture'], ['TG'], ['piece_identite','patente','preuve_revenus'], 'Groupe NSIA', 9.0, 14.0),
    ('Sunu Bank Togo', 'banque', 100000, 50000000, 500, '8-15%', ['commerce','service','agriculture'], ['TG'], ['piece_identite','patente','preuve_revenus'], 'Banque du groupe Sunu', 8.0, 15.0),
    # Banques Benin
    ('Ecobank Benin', 'banque', 100000, 50000000, 500, '9-15%', ['commerce','service','agriculture'], ['BJ'], ['piece_identite','patente','plan_affaires'], 'Banque panafricaine', 9.0, 15.0),
    ('Bank Of Africa Benin', 'banque', 100000, 50000000, 500, '9-13%', ['commerce','service','agriculture'], ['BJ'], ['piece_identite','patente','preuve_revenus'], 'Groupe BOA', 9.0, 13.0),
    ('Orabank Benin', 'banque', 100000, 50000000, 500, '9-15%', ['commerce','service','agriculture'], ['BJ'], ['piece_identite','patente','preuve_revenus'], 'Banque regionale', 9.0, 15.0),
    # Banques Cote d'Ivoire
    ('Ecobank CI', 'banque', 100000, 50000000, 500, '10-15%', ['commerce','service','agriculture','industrie'], ['CI'], ['piece_identite','patente','plan_affaires'], 'Banque panafricaine', 10.0, 15.0),
    ('Societe Generale CI', 'banque', 100000, 50000000, 500, '10-14%', ['commerce','service','agriculture'], ['CI'], ['piece_identite','patente','preuve_revenus'], 'Banque internationale', 10.0, 14.0),
    ('BOA CI', 'banque', 100000, 50000000, 500, '10-14%', ['commerce','service','agriculture'], ['CI'], ['piece_identite','patente','preuve_revenus'], 'Bank of Africa', 10.0, 14.0),
    # Banques Senegal
    ('Ecobank Senegal', 'banque', 100000, 50000000, 500, '9-15%', ['commerce','service','agriculture'], ['SN'], ['piece_identite','patente','plan_affaires'], 'Banque panafricaine', 9.0, 15.0),
    ('BOA Senegal', 'banque', 100000, 50000000, 500, '9-14%', ['commerce','service','agriculture'], ['SN'], ['piece_identite','patente','preuve_revenus'], 'Bank of Africa', 9.0, 14.0),
    # Banques Mali
    ('Ecobank Mali', 'banque', 100000, 50000000, 500, '9-15%', ['commerce','service','agriculture'], ['ML'], ['piece_identite','patente','plan_affaires'], 'Banque panafricaine', 9.0, 15.0),
    ('BOA Mali', 'banque', 100000, 50000000, 500, '10-14%', ['commerce','service','agriculture'], ['ML'], ['piece_identite','patente','preuve_revenus'], 'Bank of Africa', 10.0, 14.0),
    # Banques Burkina
    ('Ecobank Burkina', 'banque', 100000, 50000000, 500, '10-15%', ['commerce','service','agriculture'], ['BF'], ['piece_identite','patente','plan_affaires'], 'Banque panafricaine', 10.0, 15.0),
    ('BOA Burkina', 'banque', 100000, 50000000, 500, '10-15%', ['commerce','service','agriculture'], ['BF'], ['piece_identite','patente','preuve_revenus'], 'Bank of Africa', 10.0, 15.0),
    # Banques Niger
    ('Ecobank Niger', 'banque', 100000, 50000000, 500, '10-15%', ['commerce','service','agriculture'], ['NE'], ['piece_identite','patente','plan_affaires'], 'Banque panafricaine', 10.0, 15.0),
    ('BOA Niger', 'banque', 100000, 50000000, 500, '10-15%', ['commerce','service','agriculture'], ['NE'], ['piece_identite','patente','preuve_revenus'], 'Bank of Africa', 10.0, 15.0),
    # Fintechs
    ('Orange Money Credit', 'fintech', 10000, 500000, 200, '36-60%', ['commerce','service','elevage'], ['TG','BJ','CI','SN','ML','BF','NE'], ['piece_identite'], 'Credit mobile instantane', 36.0, 60.0),
    ('MTN MoMo Credit', 'fintech', 10000, 500000, 200, '36-60%', ['commerce','service','agriculture'], ['TG','BJ','CI'], ['piece_identite'], 'Credit mobile MoMo', 36.0, 60.0),
    ('Wave Credit', 'fintech', 5000, 1000000, 250, '24-48%', ['commerce','service'], ['SN','CI','ML','BF'], ['piece_identite'], 'Credit mobile Wave', 24.0, 48.0),
    ('Alafia Credit', 'fintech', 5000, 200000, 150, '100-260%', ['commerce','service'], ['TG'], ['piece_identite'], 'Micro-credit journalier', 100.0, 260.0),
    ('Oko Finance', 'fintech', 10000, 1000000, 200, '100-180%', ['commerce','agriculture','service','elevage'], ['TG'], ['piece_identite'], 'Credit mobile rapide', 100.0, 180.0),
]

cur.execute("DELETE FROM partners")
for p in partners:
    cur.execute(
        """INSERT INTO partners (name, type, min_amount, max_amount, min_score, rate, sectors, countries, docs, description, base_rate, max_rate)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", p)

# -- products (produits de credit par partenaire)
cur.execute("SELECT id, name FROM partners")
partner_ids = {r[1]: r[0] for r in cur.fetchall()}

mfi_products = {
    'FUCEC-Togo': [
        ('Credit Epargne', 50000, 3000000, 6, 36, 12.0, False,
         ['etre_membre', 'piece_identite', 'preuve_revenus'],
         'Credit sur epargne, remboursement flexible'),
        ('Credit Equipement', 100000, 5000000, 3, 24, 15.0, True,
         ['piece_identite', 'devis_materiel', 'apport_20pct'],
         'Financement materiel professionnel'),
    ],
    'WAGES Togo': [
        ('Credit Femmes Actives', 30000, 2000000, 3, 18, 10.0, False,
         ['piece_identite', 'attestation_activite', 'photo_commerce'],
         'Reserve aux femmes commerçantes'),
        ('Credit Agriculture', 50000, 3000000, 6, 24, 12.0, True,
         ['piece_identite', 'titre_terre', 'plan_culture'],
         'Financement campagne agricole'),
    ],
    'Cofina Togo': [
        ('Credit Rapid', 30000, 1000000, 1, 12, 15.0, False,
         ['piece_identite', 'preuve_revenus'],
         'Credit rapide sans garantie'),
        ('Credit Developpement', 200000, 3000000, 6, 36, 18.0, True,
         ['piece_identite', 'garantie', 'plan_affaires'],
         'Credit croissance TPE'),
    ],
    'BAOBAB Togo': [
        ('Credit Baobab', 50000, 3000000, 3, 24, 14.0, False,
         ['piece_identite', 'preuve_revenus', 'photo_activite'],
         'Credit general microfinance'),
        ('Credit Groupe', 100000, 5000000, 6, 30, 12.0, True,
         ['piece_identite', 'caution_solidaire'],
         'Credit solidaire avec caution groupe'),
    ],
    'Advans CI': [
        ('Credit Commerce', 25000, 2000000, 3, 18, 18.0, False,
         ['piece_identite', 'preuve_revenus', 'photo_commerce'],
         'Credit pour commerçants'),
        ('Credit Artisanat', 50000, 1500000, 3, 12, 20.0, True,
         ['piece_identite', 'garantie'],
         'Credit equipement artisanal'),
    ],
    'MECREF Togo': [
        ('Credit Solidarite', 20000, 1000000, 1, 12, 15.0, False,
         ['piece_identite', 'photo_activite'],
         'Credit groupe de solidarite'),
    ],
    "Fin'Elle Togo": [
        ('Credit Femme Active', 25000, 2000000, 3, 12, 14.0, False,
         ['piece_identite', 'attestation_activite'],
         'Credit dedie aux femmes'),
    ],
}

cur.execute("DELETE FROM products")
for name, products in mfi_products.items():
    pid = partner_ids.get(name)
    if not pid:
        continue
    for prod in products:
        cur.execute(
            """INSERT INTO products (partner_id, name, min_amount, max_amount, min_duration_months, max_duration_months,
               annual_rate, collateral_required, requirements, description) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (pid,) + prod)

# Produits generiques pour les banques
for pname, pid in partner_ids.items():
    if pname in mfi_products or pname.startswith(('Orange','MTN','Wave','Alafia','Oko')):
        continue
    cur.execute(
        """INSERT INTO products (partner_id, name, min_amount, max_amount, min_duration_months, max_duration_months,
           annual_rate, collateral_required, requirements, description) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (pid, 'Credit Standard', 100000, 10000000, 3, 36, 12.0, True,
         ['piece_identite', 'patente', 'preuve_revenus', 'plan_affaires'],
         'Credit standard'))

# Produits fintechs
for pname, pid in partner_ids.items():
    if not pname.startswith(('Orange','MTN','Wave','Alafia','Oko')):
        continue
    cur.execute(
        """INSERT INTO products (partner_id, name, min_amount, max_amount, min_duration_months, max_duration_months,
           annual_rate, collateral_required, requirements, description) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (pid, 'Credit Mobile', 5000, 500000, 1, 6, 48.0, False,
         ['piece_identite'],
         'Credit mobile instantane sans garantie'))

# -- knowledge_base
cur.execute("DELETE FROM knowledge_base")
kb_entries = [
    ('regle_score', 'Revenu minimum',
     'Un score de solvabilite ne devrait pas depasser 50% du ratio remboursement/revenu. La mensualite ne doit pas exceder 40% du revenu mensuel.'),
    ('regle_score', 'Marche informel',
     'Le marche informel represente 80% de l economie en Afrique de l Ouest. L absence de bulletin de salaire n est pas un risque en soi pour les TPE.'),
    ('regle_score', 'Collateral',
     'Sans collateral, le pret maximum est de 6x le revenu mensuel. Avec collateral solide (terrain, boutique, vehicule), jusqu a 24x.'),
    ('regle_score', 'Historique credit',
     'Un historique de credit positif (remboursements a temps) augmente le score de 50 points. Un defaut de paiement anterieur reduit le score de 100 points.'),
    ('regle_verification', 'Verification identite',
     'Documents acceptes: passeport, carte nationale, permis de conduire. Tous doivent etre en cours de validite.'),
    ('regle_verification', 'Verification revenus',
     'Preuve de revenus acceptee: releve mobile money 3 mois, carnet de vente, attestation client.'),
    ('marche', 'Taux UEMOA',
     'Le taux directeur BCEAO est a 3.50%. Les banques commerciales prennent entre 8% et 18% selon le profil. Les microfinances entre 10% et 24%.'),
    ('marche', 'Marches prioritaires',
     'Le Togo est le marche prioritaire. Benin, Cote d Ivoire et Senegal sont les marches secondaires.'),
    ('partenaire', 'Documents requis standard',
     'Tout dossier de credit necessite: piece d identite, preuve de revenus, photo d activite. Pour les montants >5MF: patente et plan d affaires.'),
    ('partenaire', 'Delai traitement',
     'Le delai de traitement standard est de 48-72h pour les microfinances, 1-2 semaines pour les banques.'),
]
for cat, title, content in kb_entries:
    cur.execute("INSERT INTO knowledge_base (category, title, content) VALUES (%s, %s, %s)", (cat, title, content))

conn.commit()

cur.execute("SELECT type, COUNT(*) FROM partners GROUP BY type ORDER BY type")
for t, c in cur.fetchall():
    print(f"  {t}: {c}")
cur.execute("SELECT COUNT(*) FROM products")
print(f"Produits: {cur.fetchone()[0]}")
cur.execute("SELECT COUNT(*) FROM knowledge_base")
print(f"Knowledge base: {cur.fetchone()[0]} entrees")
cur.execute("SELECT COUNT(*) FROM partners")
print(f"Total partenaires: {cur.fetchone()[0]}")
conn.close()
