# CREDO — Backlog de développement
**Companion du document "Plan Produit & Architecture Technique"**

Légende priorité : 🔴 Critique (bloquant) · 🟠 Important · 🟡 Amélioration

---

## EPIC 0 — Fondations techniques

### 0.1 🔴 Audit du MVP existant
- [ ] Cartographier le code actuel (frontend, backend, schéma Neon, prompts Groq)
- [ ] Identifier si un paiement est déjà intégré ou simulé
- [ ] Documenter les endpoints/API existants
- [ ] Lister la dette technique (couplage LLM/scoring, absence de tests, etc.)

### 0.2 🔴 Mise en place environnements
- [ ] Environnements séparés dev / staging / prod (branches Neon)
- [ ] CI/CD (build, tests, déploiement)
- [ ] Gestion des secrets (clés Groq, clés agrégateur paiement)
- [ ] Monitoring erreurs (Sentry) + logs structurés

---

## EPIC 1 — Catalogue Partenaires (back-office)

### 1.1 🔴 Modèle de données `partners` / `products`
- [ ] Schéma versionné (historique des taux/conditions)
- [ ] Champs structurés : secteur, formel/informel, revenu min, montant min/max, durée, taux, garanties, documents requis, zone géographique
- [ ] Migration des données partenaires existantes (si en dur dans le code/prompt)

### 1.2 🔴 Interface CRUD back-office
- [ ] Authentification admin (rôles : super-admin, gestionnaire partenaires)
- [ ] Formulaire création/édition produit avec validation
- [ ] Historique des modifications (audit log)
- [ ] Statut `last_verified_at` + alertes de péremption (ex. > 30 jours sans revérification)

### 1.3 🟠 Portail partenaire (self-service)
- [ ] Accès partenaire pour mettre à jour lui-même ses produits (avec validation admin avant publication)
- [ ] Statistiques partenaire (nombre de matchs, taux de conversion)

---

## EPIC 2 — Orchestrateur de conversation

### 2.1 🔴 Machine à états du parcours
- [ ] Définir les états : intake → sélection produits candidats → questions dynamiques → documents → score → rapport → paywall/mise en relation
- [ ] Persistance de l'état de session (reprise possible si interruption)

### 2.2 🔴 Sélection dynamique des questions
- [ ] Algorithme de sélection des critères discriminants restants selon les produits candidats
- [ ] Séparation claire : moteur de règles décide QUOI demander, LLM (Groq) reformule COMMENT le demander
- [ ] Gestion des profils informels (adaptation du vocabulaire, pas de jargon bancaire)

### 2.3 🟠 Gestion des documents
- [ ] Upload sécurisé (pièce d'identité, preuve de revenus, devis, justificatif domicile)
- [ ] Stockage chiffré (S3-compatible)
- [ ] Vérification basique (format, lisibilité) — OCR optionnel en V2

### 2.4 🟡 Fallback multi-provider IA
- [ ] Intégration d'un second provider LLM en secours de Groq
- [ ] Bascule automatique en cas d'indisponibilité/latence excessive

---

## EPIC 3 — Moteur de scoring

### 3.1 🔴 Modèle de scoring déterministe
- [ ] Définir la grille de pondération (revenu, stabilité, secteur, garanties, historique)
- [ ] Implémentation en module isolé, testable unitairement (pas dans le prompt LLM)
- [ ] Génération des `explanations_json` (pourquoi ce score)

### 3.2 🔴 Matching produit
- [ ] Calcul d'éligibilité par produit (éligible / partiel / non éligible)
- [ ] Calcul des mensualités estimées par offre
- [ ] Classement des meilleures options (comparatif personnalisé)

### 3.3 🟠 Feedback loop de calibrage
- [ ] Table `outcomes` (résultat réel côté partenaire)
- [ ] Interface pour que le partenaire (ou l'utilisateur) confirme le résultat réel
- [ ] Tableau de bord interne comparant score prédit vs résultat réel (base du recalibrage futur)

---

## EPIC 4 — Génération de rapport

### 4.1 🔴 Template rapport Simple
- [ ] Score, montant estimé, institution recommandée
- [ ] Génération PDF (Puppeteer/WeasyPrint)

### 4.2 🔴 Template rapport Complet
- [ ] Tous les éléments du Simple
- [ ] Comparatif multi-partenaires détaillé
- [ ] Documents manquants + conseils personnalisés
- [ ] Section "qu'est-ce qui bloque et comment l'améliorer"

### 4.3 🟡 Rédaction assistée par LLM
- [ ] Génération des paragraphes explicatifs à partir des données calculées (jamais des chiffres générés librement)
- [ ] Relecture/contrôle qualité automatique (cohérence chiffres texte vs données structurées)

---

## EPIC 5 — Paiement

### 5.1 🔴 Intégration agrégateur (CinetPay ou Semoa)
- [ ] Interface abstraite `PaymentProviderPort`
- [ ] Création intention de paiement (Simple/Complet)
- [ ] Gestion des webhooks (confirmation, échec, timeout)
- [ ] Idempotence stricte (déduplication par transaction_id)

### 5.2 🔴 Réconciliation
- [ ] Job quotidien de réconciliation paiements vs rapports générés
- [ ] Alerte en cas de paiement confirmé sans rapport livré (et inversement)

### 5.3 🟠 Commission partenaires
- [ ] Table `commissions` liée aux `matches` finalisés
- [ ] Processus de déclaration/validation manuelle au départ (automatisation plus tard)
- [ ] Reporting commissions par partenaire/période

### 5.4 🟡 Second agrégateur (redondance / expansion)
- [ ] Intégration d'un second provider (ex. Semoa si CinetPay est le premier)
- [ ] Bascule automatique en cas d'indisponibilité

---

## EPIC 6 — Mise en relation avec les partenaires

### 6.1 🔴 Flux de transmission de dossier
- [ ] Sélection du/des partenaires pertinents selon forfait (1 pour Simple, plusieurs pour Complet)
- [ ] Transmission sécurisée du dossier (accès limité aux données pertinentes)
- [ ] Notification partenaire (email/API/portail)

### 6.2 🟠 Suivi du dossier
- [ ] Statut de la mise en relation visible côté utilisateur (en cours, accepté, refusé)
- [ ] Relance automatique si pas de retour partenaire sous X jours

---

## EPIC 7 — Sécurité & conformité

### 7.1 🔴 Protection des données personnelles
- [ ] Chiffrement au repos des documents sensibles
- [ ] Politique de rétention/suppression définie et appliquée
- [ ] Consentement explicite avant collecte de données financières

### 7.2 🔴 Cadrage juridique
- [ ] Validation du statut de courtier/apporteur d'affaires (pas établissement de crédit/paiement)
- [ ] CGU/CGV conformes, mentions légales Origin SARL
- [ ] Vérification conformité avec la réglementation BCEAO/UEMOA applicable

### 7.3 🟠 Contrôle d'accès interne
- [ ] Rôles back-office (admin, gestionnaire partenaires, support)
- [ ] Journalisation des accès aux dossiers sensibles

---

## EPIC 8 — Expérience utilisateur

### 8.1 🟠 Tableau de bord utilisateur
- [ ] Historique des analyses/rapports
- [ ] Statut des mises en relation en cours
- [ ] Téléchargement des rapports précédents

### 8.2 🟡 Notifications
- [ ] SMS/WhatsApp pour statut paiement, rapport prêt, retour partenaire
- [ ] Rappels si dossier incomplet

### 8.3 🟡 Accessibilité / faible connectivité
- [ ] Mode dégradé pour connexions lentes (optimisation payload, images légères)
- [ ] Support USSD ou WhatsApp comme canal alternatif (exploration)

---

## EPIC 9 — Étage 2 : Assistant financier gamifié

### 9.1 🟠 Modèle de données `goals` / `milestones`
- [ ] Schéma objectifs multiples par utilisateur (maison, études, business, voyage)
- [ ] Paliers de progression liés à des actions réelles (prêt remboursé, épargne, document ajouté)

### 9.2 🟠 Logique de déblocage
- [ ] Règles de déblocage de nouveaux produits/options selon palier atteint
- [ ] Notifications proactives au moment opportun (produit pertinent débloqué)

### 9.3 🟡 Interface gamifiée
- [ ] Visualisation de la progression (jauge, badges, étapes)
- [ ] Suivi multi-projets en parallèle

### 9.4 🟡 Ingestion continue de données financières
- [ ] Mécanisme de mise à jour du profil dans le temps (déclaratif périodique, documents actualisés)
- [ ] Recalcul du score au fil du temps (pas uniquement à la demande)

---

## EPIC 10 — Expansion régionale (préparation)

### 10.1 🟡 Multi-pays
- [ ] Champ zone géographique sur `products`
- [ ] Gestion multi-devises si nécessaire (XOF partagé UEMOA facilite cette étape)
- [ ] Sélection dynamique de l'agrégateur de paiement selon le pays

---

## Séquencement suggéré

| Phase | Contenu | Objectif |
|---|---|---|
| **Phase A — Fiabilisation** | Epics 0, 1.1–1.2, 2.1–2.2, 3.1–3.2, 4.1–4.2, 5.1–5.2, 7.1–7.2 | Un MVP robuste, auditable, avec paiement fiable et catalogue structuré |
| **Phase B — Industrialisation** | Epics 1.3, 2.3–2.4, 3.3, 4.3, 5.3–5.4, 6, 7.3, 8.1–8.2 | Back-office complet, feedback loop, commissions, expérience utilisateur |
| **Phase C — Etage 2** | Epic 9 | Assistant gamifié, rétention long terme |
| **Phase D — Expansion** | Epic 10, 8.3 | Nouveaux marchés UEMOA |

Chaque epic peut être découpé en tickets de sprint (1–2 semaines) selon la taille de l'équipe de développement.
