"""Add products + knowledge_base tables and seed data."""
import sys
import psycopg2

DSN = sys.argv[1] if len(sys.argv) > 1 else None
if not DSN:
    print("Pass DSN as argument")
    sys.exit(1)

conn = psycopg2.connect(DSN)
cur = conn.cursor()

# Products table
cur.execute("""
    CREATE TABLE IF NOT EXISTS products (
        id SERIAL PRIMARY KEY,
        partner_id INTEGER REFERENCES partners(id),
        name TEXT NOT NULL,
        type TEXT DEFAULT 'credit',
        min_amount INTEGER DEFAULT 0,
        max_amount INTEGER DEFAULT 50000000,
        min_duration_months INTEGER DEFAULT 1,
        max_duration_months INTEGER DEFAULT 60,
        annual_rate NUMERIC(5,2),
        collateral_required BOOLEAN DEFAULT false,
        requirements TEXT[] DEFAULT ARRAY[]::TEXT[],
        description TEXT,
        created_at TIMESTAMP DEFAULT NOW()
    )
""")
cur.execute('CREATE INDEX IF NOT EXISTS idx_products_partner ON products(partner_id)')

# Seed MFI products
cur.execute("SELECT id, name, min_amount, max_amount FROM partners WHERE type = 'microfinance'")
partners_map = {r[1]: r for r in cur.fetchall()}

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
}

for name, products in mfi_products.items():
    if name not in partners_map:
        print(f"  SKIP {name}: not in partners")
        continue
    pid = partners_map[name][0]
    for prod in products:
        cur.execute(
            "INSERT INTO products (partner_id, name, min_amount, max_amount, min_duration_months, max_duration_months, annual_rate, collateral_required, requirements, description) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (pid,) + prod
        )

# Seed knowledge base
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
    cur.execute(
        "INSERT INTO knowledge_base (category, title, content) VALUES (%s, %s, %s)",
        (cat, title, content)
    )

conn.commit()

cur.execute('SELECT COUNT(*) FROM products')
print("Produits: {}".format(cur.fetchone()[0]))
cur.execute('SELECT COUNT(*) FROM knowledge_base')
print("Knowledge base: {} entrees".format(cur.fetchone()[0]))
conn.close()
