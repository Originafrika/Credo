# Revue de Projet : Credo — Courtier Crédit IA

## 1. Analyse de l'Architecture Technique

### Points Forts
- **Stack Moderne & Légère** : L'utilisation de Flask pour le backend et Groq (Llama 3.3/4) pour l'IA permet une grande rapidité de développement et une latence réduite.
- **Base de Données Scalable** : Neon (Postgres) est un excellent choix pour une architecture serverless, offrant flexibilité et performance.
- **Logique Métier Séparée** : La séparation entre `app.py` (routage) et `credo_ai.py` (intelligence) facilite la maintenance.

### Points de Vigilance
- **Incohérence du Schéma DB** : Le schéma réellement initialisé dans `app.py` est beaucoup plus minimaliste que celui décrit dans `docs/001_schema.sql`. Plusieurs tables (profiles, lenders, loan_matches) ne sont jamais créées ni utilisées.
- **Gestion des Secrets** : Bien que les clés d'API soient récupérées via des variables d'environnement, il manque une validation stricte au démarrage (le crash est possible si `GROQ_API_KEY` manque).
- **Redondance des Templates** : Présence de `chat.html` et `chat_new.html` avec des logiques de frontend différentes. `chat_new.html` semble être la version cible mais la transition n'est pas totalement finalisée.

## 2. Viabilité du Produit

### Analyse du Flow Utilisateur
- **Paiement Bloquant** : Le flow force le paiement dès l'entrée (`/chat/new`). C'est un pari audacieux (B2C direct). Pour la viabilité, il pourrait être intéressant de proposer un "micro-score" gratuit pour engager l'utilisateur avant de demander 2,500 ou 5,000 FCFA.
- **Confiance & Preuve Sociale** : La landing page est propre, mais le passage au chat est brutal. L'ajout d'une étape de vérification OTP (prévue dans le plan mais non implémentée) renforcerait le sérieux de l'application.

### Stratégie de Revenus
- Le modèle de commission partenaire (phase 3) est le plus prometteur, mais il nécessite une base de données "lenders" peuplée et à jour, ce qui n'est pas encore le cas dans le code actuel (la fonction `_get_partners` tente de requêter Neon mais les données semblent fixes ou absentes).

## 3. Efficacité de l'IA Credo

### Forces du Scoring
- L'approche hybride (règles de calcul déterministes pour le montant max + analyse LLM pour le risque et les conseils) est excellente pour la fiabilité financière.
- L'utilisation de `Llama-4-Scout` pour la vision est un atout majeur pour l'analyse des documents informels.

### Faiblesses & Risques
- **Hallucinations de Taux** : Sans un RAG (Retrieval Augmented Generation) robuste sur les produits réels des banques, l'IA risque d'inventer des taux ou des conditions qui décevront l'utilisateur final.
- **Extraction de Données** : La fonction `_extract_numbers` est un peu fragile face à des formats de monnaie variés (ex: "5 millions", "5.000.000", "5000k").

## 4. Recommandations Prioritaires

1. **Alignement DB** : Implémenter le schéma complet de `docs/001_schema.sql` pour permettre un matching réel avec les institutions financières.
2. **Robustesse IA** :
   - Renforcer les prompts pour exiger des sources systématiques sur les taux.
   - Améliorer l'extraction de données financières avec une validation par étapes.
3. **Sécurité & Stabilité** :
   - Ajouter un middleware de validation des entrées utilisateur.
   - Centraliser la gestion des erreurs pour éviter d'afficher des erreurs LLM brutes au client.
4. **Optimisation Mobile** : Dans le contexte UEMOA, s'assurer que le chat est extrêmement léger en données mobiles (optimiser le poids des templates et éviter les scripts externes lourds).

---
*Revue réalisée par Jules, Ingénieur Software Senior.*
