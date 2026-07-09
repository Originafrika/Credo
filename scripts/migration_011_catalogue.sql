-- =============================================================
-- Migration 011 — Catalogue Partenaires versionné
-- Epic 1.1: Ajout versioning + champs structurés aux produits
-- =============================================================

-- 1. Partners: ajout champs de gestion
ALTER TABLE partners ADD COLUMN IF NOT EXISTS active BOOLEAN DEFAULT true;
ALTER TABLE partners ADD COLUMN IF NOT EXISTS last_verified_at TIMESTAMPTZ;

-- 2. Products: ajout versioning
ALTER TABLE products ADD COLUMN IF NOT EXISTS version INTEGER DEFAULT 1;
ALTER TABLE products ADD COLUMN IF NOT EXISTS superseded_at TIMESTAMPTZ;
ALTER TABLE products ADD COLUMN IF NOT EXISTS min_income INTEGER;
ALTER TABLE products ADD COLUMN IF NOT EXISTS sector_tags TEXT[];
ALTER TABLE products ADD COLUMN IF NOT EXISTS formal_required BOOLEAN DEFAULT false;
ALTER TABLE products ADD COLUMN IF NOT EXISTS required_guarantees TEXT[];
ALTER TABLE products ADD COLUMN IF NOT EXISTS last_verified_at TIMESTAMPTZ;

-- 3. Index pour requêtes temps réel (uniquement produits actifs)
CREATE INDEX IF NOT EXISTS idx_products_active ON products(superseded_at) WHERE superseded_at IS NULL;

-- 4. Index pour alertes de péremption
CREATE INDEX IF NOT EXISTS idx_products_stale ON products(last_verified_at) WHERE superseded_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_partners_stale ON partners(last_verified_at) WHERE active = true;

-- 5. Initialiser les produits existants comme version 1
UPDATE products SET version = 1 WHERE version IS NULL;

-- 6. Initialiser les partenaires existants comme actifs
UPDATE partners SET active = true WHERE active IS NULL;
