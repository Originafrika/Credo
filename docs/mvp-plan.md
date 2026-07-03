# Credo — MVP Plan

**Date:** 2026-07-03
**Deadline:** Djanta AUJOURD'HUI — landing au minimum

## Phases

### Phase 1: Landing + Paiement (Aujourd'hui — AVANT Djanta)
- [x] Concept + VAOS docs créés
- [ ] Landing page: hero, how it works, pricing, CTA
- [ ] Formulaire inscription (téléphone + OTP)
- [ ] Paiement Mobile Money (Flooz, Moov, TMoney) — simulation ou API
- [ ] Deploy to Railway/Render

### Phase 2: Chat IA + Documents (Ce soir / Demain)
- [ ] Chat IA avec questions adaptatives
- [ ] Upload documents (ID, preuve revenus)
- [ ] OCR + extraction données
- [ ] Moteur scoring basique

### Phase 3: RAG Partenaires (Cette semaine)
- [ ] Base vectorielle règles partenaires
- [ ] RAG avec règles FUCEC simulées
- [ ] Matching utilisateur-partenaire
- [ ] Rapport PDF

### Phase 4: Production (Semaine prochaine)
- [ ] Partenaires réels
- [ ] Paiement Mobile Money live
- [ ] Analytics
- [ ] SEO

## Stack MVP
- **Frontend:** Single HTML page (Tailwind CSS via CDN)
- **Backend:** Python Flask
- **Paiement:** Simulation d'abord, intégration API réelle ensuite
- **Déploiement:** Railway

## Landing Page Sections
1. Hero: "Vérifie ta solvabilité en 5 minutes. Obtiens ton crédit."
2. How it works: 3 étapes (Paie → Chat → Résultat)
3. Pricing: Rapport Simple 2,500 FCFA | Complet 5,000 FCFA
4. FAQ
5. CTA: "Commencer"

## Revenue Confirmation
- Pas de gratuit
- 2,500-5,000 FCFA par rapport
- Commission partenaire (phase 2)
