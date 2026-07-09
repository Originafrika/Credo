# CREDO — Plan Produit & Architecture Technique
**Origin SARL · Lomé, Togo · Juillet 2026**

---

## 1. Brainstorm — ce que Credo est vraiment

Credo n'est pas un simulateur de crédit. C'est une **couche d'intermédiation intelligente** entre une demande de financement exprimée en langage naturel et un inventaire structuré de produits financiers (banques, IMF, fintechs). Trois idées structurent tout le reste :

1. **Le besoin pilote le questionnaire, pas l'inverse.** Un formulaire générique (comme les scoring bancaires classiques) échoue avec l'informel. Credo doit interroger sa base partenaires *avant* de poser une question, pour ne demander que ce qui fait réellement varier l'éligibilité.
2. **Le rapport EST le produit, la mise en relation est la monétisation différée.** Il faut protéger la qualité perçue du rapport (étage 1) indépendamment de la conversion commerciale (commission), sinon Credo devient un simple lead-gen déguisé et perd la confiance de l'utilisateur.
3. **La donnée comportementale accumulée est l'actif à long terme.** Chaque analyse, même non convertie, enrichit un profil de crédit alternatif (credit scoring alternatif basé sur déclaratif + documents + secteur informel). C'est ce qui rend l'étage 2 (assistant gamifié) défendable — un concurrent qui copie l'UI ne peut pas copier l'historique.

### Risques à anticiper dès l'architecture
- **Confiance dans le score** : si le score ne correspond pas à ce que la banque décide réellement, Credo perd sa crédibilité. Il faut un mécanisme de feedback loop (résultat réel de la demande chez le partenaire → recalibrage du modèle).
- **Cadre réglementaire BCEAO/UEMOA** : Credo n'est pas un établissement de crédit, mais un courtier/agrégateur d'information. Il faut clarifier le statut (courtage, apporteur d'affaires) et éviter tout positionnement qui ressemblerait à de l'octroi de crédit ou à de la collecte de dépôts — cela évite un régime prudentiel lourd.
- **Paiement Mobile Money au Togo** : le paiement d'entrée (2 500 / 5 000 FCFA) est le premier point de friction et de fraude potentielle (paiement sans livraison du rapport). L'agrégateur de paiement doit être choisi pour sa fiabilité de webhook, pas seulement son taux.
- **Qualité et fraîcheur de la base partenaires** : c'est le cœur du produit. Si les taux/conditions ne sont pas à jour, tout le rapport est faux. Il faut un back-office dédié à la gestion partenaires, pas juste des lignes en base gérées à la main.

---

## 2. Recherche — écosystème et choix techniques

### 2.1 Paiement Mobile Money (Togo / UEMOA)
Le MVP actuel n'a pas d'intégration de paiement confirmée dans la description. Comparatif des agrégateurs pertinents pour le Togo :

| Agrégateur | Couverture | Frais indicatifs (PayIn) | Points forts | Points de vigilance |
|---|---|---|---|---|
| **CinetPay** | 9 pays UEMOA/CEMAC (dont Togo) | ~1,5–3,5 % | Le plus utilisé régionalement, doc API mature, dashboard solide | Frais dégressifs seulement à volume |
| **Semoa (CashPay)** | Togo, Bénin, CI, Guinée | ~2–3,5 % | Acteur historique togolais, couvre Flooz, T-Money, Mixx by Yas, cartes | Écosystème plus fermé (Dédé/WhatsApp) |
| **PayGate Global** | Togo (fondateur) | Ouverture gratuite | Pas de compte requis côté payeur, spécialiste Flooz/T-Money togolais | Couverture géographique limitée si expansion régionale |
| **FedaPay / KKiaPay / PayDunya** | Multi-pays UEMOA | ~1,5–3 % | Bonnes options si expansion Bénin/Sénégal/CI | Moins ancrés au Togo spécifiquement |

**Recommandation** : démarrer avec **CinetPay** ou **Semoa CashPay** en encaissement principal (couverture Flooz + T-Money + carte + Mixx by Yas), avec architecture de paiement **abstraite derrière une interface interne** (`PaymentProviderPort`) pour pouvoir brancher un second agrégateur sans réécrire la logique métier — utile pour la redondance (si un webhook tombe en panne) et pour l'expansion régionale (étage 2).

À surveiller : **PI-SPI** (Plateforme Interopérable du Système de Paiement Instantané, BCEAO), infrastructure régionale d'interopérabilité qui pourrait à terme simplifier l'intégration multi-opérateurs.

### 2.2 Statut réglementaire
Credo doit se positionner clairement comme **courtier / apporteur d'affaires en produits financiers**, pas comme établissement de crédit ni comme établissement de paiement (le paiement transite par un agrégateur agréé BCEAO, Credo ne détient jamais les fonds de crédit). Cela reste à faire valider par un juriste local, mais oriente l'architecture : Credo ne doit jamais stocker de solde utilisateur ni faire transiter les fonds du prêt lui-même — seulement les frais d'accès au rapport.

### 2.3 IA — Groq
Groq est déjà en place. Points d'attention pour la suite :
- **Séparation stricte** entre (a) le modèle de langage utilisé pour la conversation/génération de questions (LLM sur Groq, ex. Llama/Mixtral selon disponibilité) et (b) le moteur de scoring, qui doit être **déterministe et auditable** (règles + pondérations explicites, pas une sortie LLM brute) — un score de solvabilité ne peut pas être une hallucination.
- Le LLM sert à : comprendre le besoin en langage naturel, choisir dynamiquement les questions pertinentes, rédiger le rapport en langage clair. Le LLM **ne décide pas** du score final — il l'explique.
- Prévoir un **fallback multi-provider** (Groq + un second provider) pour la disponibilité, vu que Groq peut avoir des limites de rate/latence en pointe.

---

## 3. Architecture cible

### 3.1 Vue d'ensemble

```
┌─────────────────────────────────────────────────────────────────┐
│                        FRONTEND (Web + PWA)                     │
│   Next.js — chat conversationnel, upload docs, dashboard user   │
└───────────────┬───────────────────────────────┬─────────────────┘
                │ HTTPS/REST + SSE (streaming)   │
┌───────────────▼───────────────┐   ┌───────────▼─────────────────┐
│        API GATEWAY / BFF       │   │   ADMIN / PARTNER BACK-OFFICE│
│  Auth, rate limit, orchestration│   │  Gestion produits partenaires│
└───────┬──────────┬────────────┘   └──────────────┬───────────────┘
        │          │                                │
┌───────▼───┐ ┌────▼─────────┐ ┌───────────┐ ┌──────▼──────────┐
│ Conversation│ │ Scoring Engine│ │ Report Gen│ │ Partners Catalog│
│ Orchestrator│ │ (règles +     │ │ (PDF/HTML)│ │ Service (CRUD + │
│ (LLM/Groq)  │ │ pondération)  │ │           │ │ versioning)     │
└───────┬─────┘ └──────┬───────┘ └─────┬─────┘ └────────┬────────┘
        │              │                │                │
┌───────▼──────────────▼────────────────▼────────────────▼───────┐
│                     NEON POSTGRES (base centrale)                │
│  users · sessions · answers · documents · scores · partners ·    │
│  products · matches · reports · payments · commissions           │
└───────┬───────────────────────────────────────┬──────────────────┘
        │                                       │
┌───────▼───────────┐                 ┌─────────▼──────────────┐
│  Object Storage    │                 │  Payment Provider        │
│  (docs, pièces id, │                 │  (CinetPay / Semoa)       │
│  rapports PDF)      │                 │  Webhooks + réconciliation│
└─────────────────────┘                 └───────────────────────────┘
```

### 3.2 Composants clés à construire/renforcer

**a) Conversation Orchestrator**
Machine à états qui pilote le dialogue :
`intake_besoin → sélection_produits_candidats(base partenaires) → génération_questions_dynamiques → collecte_réponses → demande_documents → calcul_score → génération_rapport → paywall/mise_en_relation`.
- Le choix des questions doit interroger la table `product_requirements` pour ne poser que les critères discriminants restants (arbre de décision, pas un LLM qui invente les questions à chaque fois).
- Le LLM (Groq) reformule la question en langage naturel adapté au profil (formel/informel), mais la **liste des critères à couvrir vient du moteur de règles**, pas du LLM seul — sinon deux utilisateurs avec le même profil objectif peuvent recevoir des rapports incohérents.

**b) Scoring Engine (séparé du LLM)**
- Modèle de score hybride : règles explicites par partenaire (seuils de revenu, secteur, garanties, ancienneté) + score de risque global pondéré (0–100) calculé par un module dédié (Python/Node, versionné, testable unitairement).
- Chaque décision de score doit être **traçable** : `score_explanations` (quel critère a pesé, de combien) pour la transparence promise dans le rapport ("Pourquoi ce score ?").
- Prévoir dès maintenant les champs pour calibrer le modèle avec le retour réel des partenaires (voir 3.2.d).

**c) Partners Catalog Service**
C'est la brique la plus critique à professionnaliser. Aujourd'hui probablement gérée manuellement en base — il faut un back-office dédié :
- CRUD produits partenaires avec **versioning** (un produit change de taux → historique conservé, les rapports déjà émis référencent la version au moment de l'émission).
- Champs structurés : type de produit, secteur cible, formel/informel, revenu min, durée, taux, garanties exigées, documents requis, montant min/max, zone géographique.
- Statut de fraîcheur (`last_verified_at`) avec alerte si un produit n'a pas été revérifié depuis X jours.

**d) Feedback Loop (résultat réel)**
- Après mise en relation, table `outcomes` : le partenaire ou l'utilisateur confirme si le prêt a été accordé, à quel taux, quel montant.
- Ce flux alimente un futur recalibrage du scoring (amélioration continue) — sans lui, Credo ne peut jamais prouver que son score est fiable.

**e) Paiement**
- `PaymentProviderPort` (interface) → implémentation CinetPay/Semoa.
- Flux : création intention de paiement → redirection/USSD Mobile Money → webhook de confirmation → déblocage de l'accès au rapport.
- Idempotence stricte sur les webhooks (déduplication par `transaction_id`), réconciliation quotidienne automatique.

**f) Génération de rapport**
- Template engine (HTML → PDF, ex. Puppeteer/WeasyPrint) piloté par les données structurées de `scores`, `matches`, `documents_manquants` — pas par une génération libre du LLM (le LLM rédige les paragraphes explicatifs à partir de données déjà calculées, jamais les chiffres eux-mêmes).

**g) Gamification / Etage 2 (préparation dès maintenant)**
- Modéliser dès la V1 les entités `goals` (objectifs utilisateur), `milestones` (paliers), `user_progress` — même non exposées en UI — pour éviter une refonte du schéma plus tard.

### 3.3 Modèle de données (extrait simplifié)

```
users(id, phone, name, sector_formal_bool, created_at)
sessions(id, user_id, package_type[simple|complet], status, created_at)
answers(id, session_id, question_key, value, created_at)
documents(id, session_id, type, storage_url, verified_bool)
partners(id, name, type[banque|imf|fintech], active_bool)
products(id, partner_id, version, name, min_income, sector_tags[],
         formal_required_bool, min_amount, max_amount, rate, duration_range,
         required_documents[], required_guarantees[], last_verified_at)
scores(id, session_id, global_score, risk_level, explanations_json)
matches(id, session_id, product_id, eligibility[eligible|partiel|non_eligible],
        estimated_monthly_payment, computed_at)
reports(id, session_id, pdf_url, package_type, generated_at)
payments(id, session_id, provider, amount, status, provider_ref, webhook_payload)
commissions(id, match_id, partner_id, amount, status)
outcomes(id, match_id, real_status, real_amount, real_rate, reported_at)
goals(id, user_id, type, target_amount, status)          -- étage 2
milestones(id, goal_id, label, unlocked_bool, unlocked_at) -- étage 2
```

### 3.4 Stack technique proposée

| Couche | Choix | Justification |
|---|---|---|
| Frontend | Next.js (React) + Tailwind | Existant probable, PWA-ready pour usage mobile-first Afrique |
| Backend API | Node.js (NestJS) ou équivalent typé | Structure modulaire claire pour séparer orchestrateur / scoring / catalog |
| Base de données | **Neon Postgres** (existant, conservé) | Serverless, branchable (utile pour environnements de test/staging) |
| IA conversationnelle | **Groq** (existant) + fallback secondaire | Latence faible, coût maîtrisé |
| Scoring | Module maison (règles + pondération), pas de LLM | Auditabilité, conformité |
| Stockage documents | S3-compatible (ex. Backblaze/Cloudflare R2) | Coût faible, pièces d'identité chiffrées au repos |
| Paiement | CinetPay ou Semoa CashPay, interface abstraite | Couverture Flooz/T-Money/Mixx by Yas |
| Génération PDF | Puppeteer / WeasyPrint | Rendu fiable de templates HTML → PDF |
| Observabilité | Sentry (erreurs) + logs structurés | Webhooks de paiement = zone à haut risque, il faut du monitoring dès le MVP |
| Sécurité documents | Chiffrement au repos + accès signé à durée limitée | Données sensibles (pièce d'identité, revenus) |

### 3.5 Sécurité & conformité — non négociable
- Chiffrement des documents d'identité et données financières au repos et en transit.
- Politique de rétention des données définie (durée de conservation des pièces d'identité).
- Consentement explicite RGPD-like / loi togolaise sur la protection des données personnelles avant collecte.
- Journalisation des accès aux données sensibles (qui a vu quel dossier, quand).
- Séparation des rôles back-office (un agent partenaire ne voit que les dossiers matchés avec lui, pas toute la base).

---

## 4. Feuille de route par étapes

1. **Consolidation MVP (étage 1 renforcé)** — fiabiliser paiement, structurer le catalogue partenaires, séparer scoring/LLM, feedback loop basique.
2. **Industrialisation** — back-office partenaires complet, observabilité, sécurité/conformité, tableau de bord utilisateur.
3. **Etage 2 — Assistant gamifié** — objectifs multi-projets, paliers, notifications proactives, ouverture progressive de produits.
4. **Expansion régionale** — abstraction déjà prête (paiement multi-provider, produits multi-pays) pour Bénin/Côte d'Ivoire.

*(Détail complet des tâches : voir document séparé "Credo — Backlog de développement".)*
