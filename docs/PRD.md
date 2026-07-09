# CREDO — Product Requirements Document (PRD)
**Origin SARL · Lomé, Togo · Juillet 2026**
**Compagnon des documents "Plan Produit & Architecture Technique" et "Backlog de développement"**

---

## 1. Résumé exécutif

Credo est un courtier crédit intelligent qui analyse le besoin de financement d'un utilisateur en langage naturel, le confronte à une base structurée de produits financiers de partenaires (banques, IMF, fintechs) en Afrique de l'Ouest, et produit un rapport de solvabilité et de matching personnalisé, avant de le mettre en relation avec les institutions pertinentes.

**Problème résolu** : aujourd'hui, obtenir un prêt en Afrique de l'Ouest exige de déposer un dossier séparé dans chaque institution, sans visibilité comparative, avec des délais longs et un résultat incertain — un frein particulièrement lourd pour le secteur informel, exclu des grilles bancaires classiques.

**Proposition de valeur** : un seul parcours conversationnel, un rapport unique qui dit clairement "es-tu finançable, où, à quelles conditions, et que faut-il améliorer" — pour le fonctionnaire comme pour le vendeur au marché.

---

## 2. Objectifs produit

| Objectif | Indicateur cible (à affiner avec la donnée réelle du MVP) |
|---|---|
| Faire payer l'accès au rapport | Taux de conversion visiteur → paiement |
| Produire un rapport perçu comme fiable | Taux de rapports jugés "utiles/clairs" (feedback post-rapport) |
| Générer des mises en relation qui aboutissent | Taux de conversion match → prêt accordé (via `outcomes`) |
| Monétiser via commission | Revenu commission / mois, % du chiffre d'affaires total |
| Construire un profil utilisateur durable (étage 2) | Taux de retour des utilisateurs (2e analyse, ajout d'objectif) |

---

## 3. Utilisateurs cibles / personas

### Persona A — "Le formel prudent"
Fonctionnaire ou salarié avec bulletin de salaire. Sait ce qu'est un crédit bancaire mais n'a pas le temps/l'envie de démarcher plusieurs banques. Cherche la meilleure offre, pas juste une offre.

### Persona B — "L'informel non bancarisé"
Vendeuse au marché, artisan, petit commerçant. N'a jamais mis les pieds dans une banque, se méfie des institutions, revenus irréguliers et non documentés formellement. A besoin d'un langage simple, de questions adaptées à sa réalité (chiffre d'affaires estimé, stock, activité) plutôt qu'à une fiche de paie.

### Persona C — "Le porteur de projet"
Objectif précis (voyage, études d'un enfant, extension de boutique). Vient avec un besoin défini en langage naturel, pas avec une connaissance des produits financiers disponibles.

### Persona D — "L'institution partenaire" (utilisateur interne/B2B)
Banque, IMF, fintech qui reçoit des dossiers déjà pré-qualifiés. A besoin de confiance dans le score transmis et d'un flux de dossier exploitable sans double saisie.

---

## 4. Parcours utilisateur (étage 1 — MVP consolidé)

1. **Arrivée & choix du forfait** — l'utilisateur choisit Simple (2 500 FCFA) ou Complet (5 000 FCFA).
2. **Paiement** — via agrégateur Mobile Money/carte (cf. Plan Architecture §2.1).
3. **Expression du besoin** — champ libre en langage naturel ("je veux financer les études de mon fils").
4. **Questions dynamiques adaptatives** — Credo interroge le catalogue partenaires pour ne poser que les critères discriminants restants ; le ton et le vocabulaire s'adaptent au profil formel/informel.
5. **Demande de documents** — uniquement ceux requis par les partenaires candidats.
6. **Calcul du score et du matching** — moteur de règles déterministe (pas le LLM).
7. **Génération du rapport** :
   - Simple → score global, niveau de risque, 1 recommandation
   - Complet → rapport multi-pages : score, éligibilité par partenaire (éligible/partiel/non éligible), taux et mensualités estimées, blocages, documents manquants, conseils d'amélioration, comparatif personnalisé
8. **Mise en relation** — transmission du dossier au(x) partenaire(s) pertinent(s) selon le forfait, si possibilité réelle de financement.
9. **Suivi** — statut de la mise en relation visible par l'utilisateur ; confirmation du résultat réel (alimente le feedback loop).
10. **Commission** — Credo facture le partenaire si le prêt est finalisé.

---

## 5. Exigences fonctionnelles

### 5.1 Conversation & intake
- FR-1 🔴 Le système doit accepter une description libre du besoin en français (et idéalement langues locales à terme).
- FR-2 🔴 Le système doit sélectionner dynamiquement les questions à poser en fonction des produits partenaires candidats, sans répéter une question déjà répondue.
- FR-3 🟠 Le système doit permettre à l'utilisateur de reprendre une session interrompue.
- FR-4 🟠 Le système doit adapter le registre de langage selon le profil détecté (formel/informel) sans jamais être condescendant.

### 5.2 Documents
- FR-5 🔴 Le système doit permettre l'upload sécurisé de documents (image/PDF) : pièce d'identité, preuve de revenus, devis, justificatif de domicile.
- FR-6 🟠 Le système doit valider basiquement le format/lisibilité du document uploadé.
- FR-7 🟡 Le système doit pouvoir extraire automatiquement certaines données (OCR) en V2.

### 5.3 Scoring & matching
- FR-8 🔴 Le système doit calculer un score de solvabilité et un niveau de risque de manière déterministe et traçable.
- FR-9 🔴 Le système doit calculer, pour chaque produit partenaire candidat, un statut d'éligibilité (éligible / partiel / non éligible) et une mensualité estimée.
- FR-10 🔴 Le système doit expliquer les facteurs qui ont influencé le score (transparence).
- FR-11 🟠 Le système doit pouvoir recalibrer ses pondérations à partir des résultats réels observés (`outcomes`).

### 5.4 Rapport
- FR-12 🔴 Le système doit générer un rapport Simple (1 recommandation) et un rapport Complet (comparatif multi-partenaires) en PDF.
- FR-13 🔴 Le rapport doit inclure : score, financabilité, blocages, documents manquants, conseils, comparatif.
- FR-14 🟠 Le rapport doit être téléchargeable et consultable ultérieurement depuis un espace utilisateur.

### 5.5 Paiement
- FR-15 🔴 Le système doit accepter le paiement via Mobile Money (Flooz, T-Money, Mixx by Yas) et carte bancaire, avant accès au rapport complet.
- FR-16 🔴 Le système doit gérer les webhooks de confirmation de paiement de manière idempotente.
- FR-17 🔴 Le système ne doit jamais livrer un rapport payant sans confirmation de paiement effective, et ne doit jamais facturer sans livrer le rapport (réconciliation quotidienne).

### 5.6 Mise en relation & commission
- FR-18 🔴 Le système doit transmettre le dossier pertinent au(x) partenaire(s) sélectionné(s) selon le forfait.
- FR-19 🟠 Le système doit permettre le suivi du statut de mise en relation par l'utilisateur.
- FR-20 🟠 Le système doit permettre l'enregistrement et le calcul de la commission due par un partenaire lors d'un prêt finalisé.

### 5.7 Back-office partenaires
- FR-21 🔴 Un administrateur doit pouvoir créer/modifier/désactiver un produit partenaire avec historique de version.
- FR-22 🟠 Un partenaire doit pouvoir mettre à jour ses propres produits (sous validation admin).
- FR-23 🟠 Le système doit alerter si un produit n'a pas été revérifié depuis un seuil de jours défini.

### 5.8 Étage 2 — gamification (hors MVP, à cadrer)
- FR-24 🟡 L'utilisateur doit pouvoir ajouter plusieurs objectifs financiers à son profil.
- FR-25 🟡 Le système doit débloquer progressivement des produits/options selon les paliers franchis.
- FR-26 🟡 Le système doit notifier l'utilisateur au moment opportun d'une nouvelle option pertinente.

---

## 6. Exigences non fonctionnelles

| Catégorie | Exigence |
|---|---|
| **Sécurité** | Chiffrement au repos des documents et données financières sensibles ; accès signé à durée limitée aux fichiers |
| **Confidentialité** | Consentement explicite avant collecte de données financières ; politique de rétention/suppression définie |
| **Conformité** | Positionnement clarifié comme courtier/apporteur d'affaires (pas établissement de crédit ni de paiement) ; conformité BCEAO/UEMOA sur les flux financiers |
| **Fiabilité paiement** | Zéro perte de transaction : idempotence stricte, réconciliation quotidienne automatique |
| **Performance** | Temps de réponse conversationnel perçu < quelques secondes (dépend de la latence Groq) ; dégradation gracieuse si LLM indisponible (fallback) |
| **Disponibilité** | Service accessible sur connexions faibles/instables (poids de page optimisé, mode dégradé) |
| **Auditabilité** | Traçabilité complète des scores (quel critère, quel poids, quelle version de produit utilisée) |
| **Scalabilité** | Architecture permettant l'ajout de nouveaux pays/partenaires sans refonte (cf. schéma multi-pays) |
| **Accessibilité** | Interface utilisable par un public non technophile ; vocabulaire simple pour les profils informels |

---

## 7. Hors périmètre (explicitement exclu du MVP consolidé)

- Octroi ou décaissement direct de crédit par Credo (Credo ne prête jamais lui-même).
- Détention de fonds ou de soldes utilisateurs (les flux de prêt transitent uniquement entre l'utilisateur et le partenaire financier).
- OCR automatique des documents (prévu en V2).
- Interface gamifiée complète de l'étage 2 (le modèle de données est préparé, l'UI ne l'est pas en Phase A/B).
- Support multi-pays actif (l'architecture le prépare, le lancement reste Togo d'abord).
- Canal USSD/WhatsApp natif (exploration seulement).

---

## 8. Risques produit & mitigations

| Risque | Impact | Mitigation |
|---|---|---|
| Score perçu comme peu fiable si décorrélé de la décision réelle du partenaire | Perte de confiance utilisateur et partenaire | Feedback loop `outcomes` + recalibrage périodique (FR-11) |
| Catalogue partenaires obsolète (taux périmés) | Rapport erroné, risque réputationnel et juridique | Versioning + alertes de péremption (FR-21, FR-23) |
| Paiement confirmé sans livraison du rapport (ou inverse) | Perte de confiance, litiges, remboursements | Idempotence + réconciliation quotidienne (FR-16, FR-17) |
| Requalification juridique en établissement de crédit/paiement | Risque réglementaire majeur | Cadrage juridique explicite du statut de courtier (cf. Plan Architecture §3.5) |
| Faible taux de conversion en environnement informel (méfiance) | Adoption limitée du persona B | Adaptation du langage, transparence sur l'usage des données, preuve sociale |

---

## 9. Séquencement (rappel, détail dans le Backlog)

Phase A — Fiabilisation MVP → Phase B — Industrialisation (back-office, feedback loop, commissions) → Phase C — Étage 2 gamification → Phase D — Expansion régionale.

Le détail tâche par tâche est dans **Credo — Backlog de développement**.
