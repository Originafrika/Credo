# Donnees Publiques — Pret UEMOA

## Sources Identifiees

### 1. BCEAO — Conditions de Banque (semestriel)
**URL:** https://ns2.bceao.int/sites/default/files/2026-04/Conditions-de-banque-Premier-semestre-2025.pdf
**Contenu:** Taux de base bancaire + taux debiteur maximum de TOUTES les banques de l'UMOA, par pays.
**Utilisation:** Alimenter `lenders` avec taux reels du marche.
**Couverture:** Banques commerciales. Pas les microfinances ni fintechs.

### 2. BCEAO — Situation Microfinance (trimestriel)
**URL:** https://www.bceao.int/sites/default/files/2026-02/Situation%20de%20la%20microfinance%20%C3%A0%20fin%20septembre%202025.pdf
**Contenu:** 527 IMF dans l'UMOA, 2.780 milliards FCFA encours credits, 2.731 milliards depots. Taux de degradation portefeuille par pays.
**Utilisation:** Benchmarking marche, identifier IMF dominantes par pays.

### 3. BCEAO — Bulletin Mensuel Statistiques
**URL:** https://downloads.bceao.int/sites/default/files/2026-04/Bulletin_mensuel_des_statistiques-Mars_2026.pdf
**Contenu:** Taux directeurs (actuel: 3.00%), masse monetaire, credits a l'economie.
**Utilisation:** Contexte macro pour scoring.

### 4. Togo — Liste SFD Agrees (2025)
**URL:** https://finances.gouv.tg/wp-content/uploads/2025/01/LISTE-ACTUALISEE-DES-SFD-.pdf
**URL site:** https://finances.gouv.tg/liste-actualisee-a-la-date-du-09-janvier-2025-des-systemes-financiers-decentralises-sfd-communement-appeles-structures-de-microfinances/
**Contenu:** 72 microfinances agreees au Togo avec contacts (tel, siege).
**Utilisation:** Seed data complete pour Togo.

### 5. CB-UMOA — Paysage des Assujettis (dec 2025)
**URL:** https://cb-umoa.org/fr/paysage-des-assujettis
**Contenu:** 293 SFD de grande taille dans l'UMOA (46 societes, 17 associations, 22 reseaux, 46 IMCEC non-affiliees, 162 caisses de base).
**Utilisation:** Panorama complet du marche microfinance UEMOA.

### 6. APSFD-Togo — Association Professionnelle SFD
**URL:** https://apsfdtogo.com/
**Contenu:** Membres, actualites du secteur microfinance Togo.

### 7. World Bank — Global Findex Database 2021
**URL:** https://microdata.worldbank.org/index.php/catalog/global-findex
**Contenu:** Donnees par pays sur inclusion financiere (comptes, epargne, credit, paiements digitaux).
**Disponible par pays:** Benin, Senegal, Cote d'Ivoire, Togo, Burkina, Mali, Niger.
**Utilisation:** Profilage marche potentiel, segments non-bancarises.

### 8. MIX Market (World Bank DataBank)
**URL:** https://databank.worldbank.org/embed/Donn%C3%A9es-/id/cf29c44e
**Contenu:** Portefeuille credits, genre, delinquance, performance IMF.
**Utilisation:** Scoring comparatif.

## Prochaine Etape: Extraction Automatique

Prochain sprint: script Python/Node qui telecharge les PDF BCEAO et extrait les donnees → seed dataset `lenders`.

```python
# Pseudo-code extraction BCEAO
bceao_pdf = download("https://ns2.bceao.int/.../Conditions-de-banque-Premier-semestre-2025.pdf")
tables = extract_tables(bceao_pdf)
for row in tables:
    # nom_banque, pays, taux_base, taux_max
    lenders.insert({name, country, type: 'banque', criteria: {...}})
```

## Notes

- BCEAO publie en PDF (pas d'API REST). Extraction = PDF parsing.
- Fintechs (Wave, Orange Money, MTN MoMo) N'APPARAISSENT PAS dans les donnees BCEAO — ce sont des EME (Etablissements de Monnaie Electronique), pas des banques. Leurs donnees sont privees.
- Pour les fintechs, les taux et criteres viennent des sites web et apps.
- Les IMF (microfinances) reunies par l'APSFD-Togo et CB-UMOA.
