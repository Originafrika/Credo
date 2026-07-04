-- ===============================================================
-- Credo Schema v1.0 — Neon Postgres
-- Courtier Credit IA pour UEMOA (Togo, Benin, CIV, Senegal...)
-- ===============================================================

-- 1. PROFILES (emprunteurs)
CREATE TABLE profiles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  phone TEXT UNIQUE NOT NULL,
  whatsapp TEXT,
  full_name TEXT NOT NULL,
  email TEXT,
  business_type TEXT,            -- commerce, agriculture, service, artisanat, eleveur
  monthly_revenue DECIMAL(12,2),
  location_country TEXT DEFAULT 'TG',
  location_city TEXT,
  registered_at TIMESTAMPTZ DEFAULT now(),
  verified_at TIMESTAMPTZ,
  risk_flag BOOLEAN DEFAULT false
);

-- 2. LENDERS (preteurs)
CREATE TABLE lenders (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  slug TEXT UNIQUE NOT NULL,
  type TEXT NOT NULL,             -- banque, microfinance, fintech, cooperative, particulier
  country TEXT[] DEFAULT '{TG}',
  min_loan DECIMAL(12,2) DEFAULT 0,
  max_loan DECIMAL(12,2),
  min_score INT DEFAULT 0,
  max_rate DECIMAL(5,2),          -- taux annuel max en %
  target_sectors TEXT[],          -- secteurs finances
  requires_collateral BOOLEAN DEFAULT false,
  requires_business_reg BOOLEAN DEFAULT false,
  max_duration_months INT,
  criteria JSONB,                 -- criteres flexibles
  active BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- 3. LOAN PRODUCTS (produits specifiques par preteur)
CREATE TABLE loan_products (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  lender_id UUID REFERENCES lenders(id),
  name TEXT NOT NULL,
  min_amount DECIMAL(12,2),
  max_amount DECIMAL(12,2),
  min_rate DECIMAL(5,2),
  max_rate DECIMAL(5,2),
  min_duration INT,               -- mois
  max_duration INT,
  requirements TEXT[],            -- documents requis
  active BOOLEAN DEFAULT true
);

-- 4. CREDIT SCORES (scoring IA)
CREATE TABLE credit_scores (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  profile_id UUID REFERENCES profiles(id),
  score INT NOT NULL CHECK (score >= 0 AND score <= 1000),
  model_version TEXT NOT NULL,
  factors JSONB,                  -- {"revenue_weight": 0.35, "sector_weight": 0.15, ...}
  confidence DECIMAL(3,2) CHECK (confidence >= 0 AND confidence <= 1),
  expires_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- 5. LOAN MATCHES (matching emprunteur vs preteurs)
CREATE TABLE loan_matches (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  profile_id UUID REFERENCES profiles(id),
  lender_id UUID REFERENCES lenders(id),
  product_id UUID REFERENCES loan_products(id),
  score_id UUID REFERENCES credit_scores(id),
  amount DECIMAL(12,2),
  estimated_rate DECIMAL(5,2),
  match_rank INT,                 -- 1 = meilleur match
  status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'interested', 'applied', 'approved', 'rejected', 'funded', 'expired')),
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- 6. DOCUMENTS (PDF, photos, scans) pipeline robuste
CREATE TABLE documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  profile_id UUID REFERENCES profiles(id) NOT NULL,
  type TEXT NOT NULL CHECK (type IN (
    'id_card', 'passport', 'driver_license',
    'business_license', 'tax_certificate',
    'bank_statement', 'mobile_money_statement',
    'invoice', 'receipt',
    'selfie', 'proof_of_address',
    'business_photo', 'collateral_photo',
    'other'
  )),
  storage_url TEXT NOT NULL,       -- Vercel Blob / R2 / S3
  original_name TEXT,
  mime_type TEXT,                  -- application/pdf, image/jpeg, image/png, image/heic
  file_size_bytes INT,
  extracted_json JSONB,            -- donnees extraites par IA
  extraction_status TEXT DEFAULT 'pending' CHECK (extraction_status IN ('pending', 'processing', 'done', 'failed', 'verified')),
  extraction_model TEXT,           -- ex: "meta-llama/llama-4-scout-17b-16e-instruct"
  extraction_confidence DECIMAL(3,2),
  verified BOOLEAN DEFAULT false,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- 7. EXTRACTION LOG (traçabilite extraction IA)
CREATE TABLE extraction_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id UUID REFERENCES documents(id),
  model TEXT NOT NULL,
  raw_response JSONB,
  fields_extracted JSONB,
  tokens_used INT,
  latency_ms INT,
  success BOOLEAN DEFAULT true,
  error_message TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- 8. ALTERNATIVE DATA (mobile money, transactions)
CREATE TABLE alternative_data (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  profile_id UUID REFERENCES profiles(id),
  source TEXT NOT NULL CHECK (source IN ('mtn_momo', 'orange_money', 'wave', 'flooz', 'free_money', 'tmoney', 'other')),
  raw JSONB,
  insights JSONB,                  -- volume mensuel, regularite, solde moyen
  ingested_at TIMESTAMPTZ DEFAULT now()
);

-- 9. EVALUATIONS (suivi parcours emprunteur)
CREATE TABLE evaluations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  profile_id UUID REFERENCES profiles(id),
  status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'payment_wait', 'documents_pending', 'analyzing', 'completed', 'expired')),
  payment_ref TEXT,
  payment_amount DECIMAL(10,2) DEFAULT 3500,
  payment_verified BOOLEAN DEFAULT false,
  started_at TIMESTAMPTZ DEFAULT now(),
  completed_at TIMESTAMPTZ
);

-- 10. PARTNERSHIPS (conventions commission avec partenaires)
CREATE TABLE partnerships (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  lender_id UUID UNIQUE REFERENCES lenders(id),
  status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'active', 'suspended', 'terminated')),
  commission_type TEXT NOT NULL CHECK (commission_type IN ('flat', 'percentage', 'tiered')),
  commission_value DECIMAL(5,2) NOT NULL,    -- montant fixe ou pourcentage
  commission_trigger TEXT DEFAULT 'funded' CHECK (commission_trigger IN ('applied', 'approved', 'funded', 'repaid')),
  contract_url TEXT,                           -- PDF convention signee
  started_at TIMESTAMPTZ,
  expires_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- 11. REFERRALS (clients envoyes aux partenaires)
CREATE TABLE referrals (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  profile_id UUID REFERENCES profiles(id),
  lender_id UUID REFERENCES lenders(id),
  match_id UUID REFERENCES loan_matches(id),
  partnership_id UUID REFERENCES partnerships(id),
  status TEXT DEFAULT 'sent' CHECK (status IN ('sent', 'viewed', 'contacted', 'applied', 'approved', 'funded', 'rejected', 'expired')),
  sent_at TIMESTAMPTZ DEFAULT now(),
  first_contact_at TIMESTAMPTZ,
  funded_at TIMESTAMPTZ,
  loan_amount DECIMAL(12,2),
  notes TEXT
);

-- 12. COMMISSIONS (revenus Credo)
CREATE TABLE commissions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  referral_id UUID UNIQUE REFERENCES referrals(id),
  partnership_id UUID REFERENCES partnerships(id),
  amount DECIMAL(12,2) NOT NULL,
  status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'due', 'paid', 'cancelled')),
  due_date TIMESTAMPTZ,
  paid_at TIMESTAMPTZ,
  invoice_ref TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Indexes
CREATE INDEX idx_profiles_phone ON profiles(phone);
CREATE INDEX idx_profiles_verified ON profiles(verified_at) WHERE verified_at IS NOT NULL;
CREATE INDEX idx_lenders_active ON lenders(active) WHERE active = true;
CREATE INDEX idx_lenders_type ON lenders(type);
CREATE INDEX idx_loan_products_lender ON loan_products(lender_id);
CREATE INDEX idx_credit_scores_profile ON credit_scores(profile_id);
CREATE INDEX idx_credit_scores_expires ON credit_scores(expires_at) WHERE expires_at > now();
CREATE INDEX idx_loan_matches_profile ON loan_matches(profile_id);
CREATE INDEX idx_loan_matches_status ON loan_matches(status);
CREATE INDEX idx_documents_profile ON documents(profile_id);
CREATE INDEX idx_documents_status ON documents(extraction_status);
CREATE INDEX idx_evaluations_profile ON evaluations(profile_id);
CREATE INDEX idx_evaluations_status ON evaluations(status);
CREATE INDEX idx_extraction_logs_doc ON extraction_logs(document_id);
CREATE INDEX idx_alternative_data_profile ON alternative_data(profile_id);
CREATE INDEX idx_partnerships_lender ON partnerships(lender_id);
CREATE INDEX idx_partnerships_status ON partnerships(status);
CREATE INDEX idx_referrals_profile ON referrals(profile_id);
CREATE INDEX idx_referrals_status ON referrals(status);
CREATE INDEX idx_referrals_partnership ON referrals(partnership_id);
CREATE INDEX idx_commissions_status ON commissions(status);
CREATE INDEX idx_commissions_referral ON commissions(referral_id);

-- ===============================================================
-- SEED DATA: Preteurs UEMOA + Produits
-- ===============================================================

-- Preteurs
INSERT INTO lenders (slug, name, type, country, min_loan, max_loan, min_score, max_rate, target_sectors, requires_collateral, requires_business_reg, max_duration_months, criteria) VALUES
('orange-money', 'Orange Money Credit', 'fintech', '{TG,BJ,CI,SN,ML,BF,NE}', 10000, 500000, 200, 60.00, '{commerce,service,elevage}', false, false, 6, '{"transactions_min": 3, "account_active_months": 3, "daily_withdrawal_limit": 500000}'),
('mtn-momo', 'MTN MoMo Credit', 'fintech', '{TG,BJ,CI,GH,UG}', 10000, 500000, 200, 60.00, '{commerce,service,agriculture}', false, false, 6, '{"transactions_min": 3, "account_active_months": 3}'),
('wave', 'Wave Credit', 'fintech', '{SN,CI,ML,BF}', 5000, 1000000, 250, 48.00, '{commerce,service}', false, false, 6, '{"account_active_months": 1, "min_balance": 1000}'),
('fucec-togo', 'FUCEC-Togo', 'microfinance', '{TG}', 50000, 5000000, 400, 18.00, '{commerce,agriculture,artisanat,elevage,service}', true, false, 24, '{"group_lending": true, "savings_account_required": true, "min_group_size": 3}'),
('wages', 'WAGES Togo', 'microfinance', '{TG}', 30000, 3000000, 350, 15.00, '{commerce,agriculture,artisanat}', false, false, 18, '{"women_only": true, "group_lending": true, "training_required": true}'),
('ubt', 'Union Bank Togo', 'banque', '{TG}', 100000, 10000000, 500, 10.00, '{commerce,service,agriculture}', true, true, 36, '{"business_reg_required": true, "collateral_min_ratio": 1.2, "min_revenue": 500000}'),
('advans-ci', 'Advans CI', 'microfinance', '{CI}', 25000, 2000000, 350, 20.00, '{commerce,artisanat,service}', true, false, 18, '{"business_plan_required": true, "min_activity_months": 6}'),
('mecref', 'MECREF Togo', 'microfinance', '{TG}', 20000, 1000000, 300, 18.00, '{commerce,agriculture,artisanat}', false, false, 12, '{"group_lending": true}'),
('baobab', 'BAOBAB Group', 'microfinance', '{SN,CI,ML,BF,TG,BJ}', 50000, 5000000, 350, 16.00, '{commerce,agriculture,service,elevage}', true, false, 24, '{"savings_account_required": true, "min_activity_months": 3}'),
('finelle', "Fin'Elle Togo", 'microfinance', '{TG}', 25000, 2000000, 300, 14.00, '{commerce,artisanat}', false, false, 12, '{"women_only": true, "group_lending": true}'),
('ecobank', 'Ecobank UEMOA', 'banque', '{TG,BJ,CI,SN,ML,BF,NE}', 500000, 50000000, 600, 8.00, '{commerce,service,agriculture,industrie}', true, true, 60, '{"business_reg_required": true, "collateral_min_ratio": 1.5, "min_revenue": 2000000, "min_activity_months": 12}'),
('coris-bank', 'Coris Bank', 'banque', '{TG,BF,CI,ML,SN}', 200000, 20000000, 500, 10.00, '{commerce,service,agriculture}', true, true, 48, '{"business_reg_required": true, "collateral_min_ratio": 1.3}'),
('cofina', 'Cofina Togo', 'microfinance', '{TG}', 30000, 3000000, 300, 18.00, '{commerce,agriculture,artisanat,elevage}', true, false, 18, '{"savings_account_required": true}'),
('alafia', 'Alafia Credit', 'fintech', '{TG}', 5000, 200000, 150, 260.00, '{commerce,service}', false, false, 1, '{"daily_repayment": true, "no_collateral": true}'),
('oko-finance', 'Oko Finance', 'fintech', '{TG}', 10000, 1000000, 200, 180.00, '{commerce,agriculture,service,elevage}', false, false, 3, '{"mobile_only": true, "quick_disbursement": true}');

-- Produits
INSERT INTO loan_products (lender_id, name, min_amount, max_amount, min_rate, max_rate, min_duration, max_duration, requirements)
SELECT id, name || ' Standard', min_loan, max_loan, max_rate * 0.8, max_rate, 1, max_duration_months, 
  CASE 
    WHEN requires_collateral AND requires_business_reg THEN ARRAY['business_license', 'id_card', 'proof_of_address', 'bank_statement', 'collateral_document']
    WHEN requires_collateral THEN ARRAY['id_card', 'proof_of_address', 'collateral_document']
    WHEN requires_business_reg THEN ARRAY['business_license', 'id_card', 'proof_of_address']
    ELSE ARRAY['id_card']
  END
FROM lenders;

-- Produit court-terme pour fintechs
INSERT INTO loan_products (lender_id, name, min_amount, max_amount, min_rate, max_rate, min_duration, max_duration, requirements)
SELECT id, name || ' Express', min_loan, max_loan * 0.5, max_rate * 0.9, max_rate, 1, 3,
  ARRAY['id_card', 'selfie']
FROM lenders WHERE type = 'fintech';

-- ===============================================================
-- NOTES:
-- - Montants en FCFA
-- - scores: 0-1000 (0=risque max, 1000=risque min)
-- - rates: taux ANNUEL en % (fintech = taux eleve car court terme)
-- - Voir docs/002_document_pipeline.md pour pipeline extraction
-- ===============================================================
