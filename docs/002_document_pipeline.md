# Document Pipeline — Credo

## Objectif
Transformer tout document (PDF, photo JPG/PNG/HEIC, scan) en donnees structurees pour l'IA de scoring. Robustesse = pas de format refuse, pas de champ perdu.

## Flux

```
Upload → Vercel Blob → Worker → Extraction IA → Validation → DB
```

## 1. Upload (Next.js API Route)

```typescript
// POST /api/documents/upload
// Body: form-data { file: Blob, profile_id: UUID, doc_type: string }
// Validation: taille max 20MB, types acceptes
// Stockage: Vercel Blob (https://blob.vercel.com)
// Retour: { document_id, upload_url }
```

Types documents acceptes:
- `id_card` — CNI, passeport, permis
- `business_license` — patente, registre commerce
- `bank_statement` — releve bancaire (PDF)
- `mobile_money_statement` — historique MTN/Orange/Wave
- `invoice` — facture, devis
- `receipt` — recu, ticket
- `selfie` — photo du visage (verification)
- `proof_of_address` — facture eau/electricite
- `business_photo` — photo du commerce/boutique
- `collateral_photo` — photo du collateral

## 2. Stockage (Vercel Blob)

- Bucket unique: `credo-documents`
- Path: `{profile_id}/{doc_id}_{original_name}`
- Metadata: doc_type, original_format, upload_timestamp

## 3. Post-Upload Worker (Optionnel: Cloudflare Worker ou Route Next.js)

Worker ou route:
1. Detecte format (magic bytes, pas extension)
2. Si photo HEIC → convertit en JPEG
3. Si PDF > 5 pages → extrait les 5 premieres pages seulement
4. Si photo floue → detecte via variance Laplacian
5. Prepare payload pour extraction IA

```typescript
// Detection format
const detectFormat = (buffer: ArrayBuffer): string => {
  const magic = new Uint8Array(buffer.slice(0, 4));
  // 255 216 255 = JPEG, 137 80 78 71 = PNG, 0 0 0 18 ftyp = HEIC, 37 80 68 70 = PDF
};

// Pre-processing
const preprocess = async (buffer, mime) => {
  if (mime === 'image/heic') return await convertHeicToJpeg(buffer);
  if (mime === 'application/pdf') return await limitPdfPages(buffer, 5);
  if (isBlurry(buffer)) return { error: 'image_floue', retry: true };
  return buffer;
};
```

## 4. Extraction IA (Groq Vision)

Appel a Groq API avec modele vision pour extraire les champs.

```typescript
// POST https://api.groq.com/openai/v1/chat/completions
// Model: meta-llama/llama-4-scout-17b-16e-instruct (vision, JSON mode, 750 t/s)
//         qwen/qwen3.6-27b (vision alternative, +cher mais +precis)

const extractFields = async (imageUrl: string, docType: string) => {
  const prompt = buildPrompt(docType);
  const response = await groq.chat.completions.create({
    model: "meta-llama/llama-4-scout-17b-16e-instruct",
    messages: [
      {
        role: "user",
        content: [
          { type: "text", text: prompt },
          { type: "image_url", image_url: { url: imageUrl } }
        ]
      }
    ],
    response_format: { type: "json_object" },
    temperature: 0.1
  });
  return JSON.parse(response.choices[0].message.content);
};
```

Limites: 5 images par requete, 20MB max par URL, 33 megapixels max par image.

### Prompts par type de document

**id_card:**
Extraction: nom, prenom, date_naissance, lieu_naissance, numero_piece, date_expiration, sexe

**bank_statement:**
Extraction: institution, titulaire_compte, periode_debut, periode_fin, solde_moyen, transactions_entrantes (montant total, nombre), transactions_sortantes (montant total, nombre), credits_salaires (montant, regularite)

**mobile_money_statement:**
Extraction: operateur (MTN/Orange/Wave), numero, periode, solde_moyen, transactions_entrantes, transactions_sortantes, regularite_jours_sans_transaction

**business_license:**
Extraction: nom_entreprise, numero_rcm, date_creation, siege_social, activite

**proof_of_address:**
Extraction: nom, adresse, type_facture (eau/electricite/telephone), date, montant

**selfie:**
Verification: detection_visage (true/false), qualite (bonne/moyenne/mauvaise), probabilite_vivant

**business_photo:**
Extraction: type_commerce (boutique/atelier/restaurant/etal), estimation_taille, etat_local

## 5. Validation & Stockage

```typescript
// Validation croisee
const validateExtraction = (extracted: any, docType: string) => {
  const required = getRequiredFields(docType);
  const missing = required.filter(f => !extracted[f]);
  const confidence = missing.length === 0 ? 0.95 : 0.5;
  return { valid: missing.length === 0, missing, confidence };
};

// Stockage en DB
await db.insert(documents).values({
  id: doc_id,
  profile_id,
  type: doc_type,
  storage_url,
  mime_type,
  file_size_bytes,
  extracted_json: extracted,
  extraction_status: 'done',
  extraction_model: 'meta-llama/llama-4-scout-17b-16e-instruct',
  extraction_confidence: confidence
});
```

## 6. Fallbacks et Robustesse

| Probleme | Solution |
|----------|----------|
| Photo floue | Detection Laplacian, demande re-upload |
| PDF crypte | Bloque a l'upload |
| Photo nuit/obscure | Correction gamma auto, sinon demande re-upload |
| Extraction echoue (JSON malforme) | 3 tentatives, si fails → fallback extraction texte pur |
| Document en langue locale (ewe, kabiye) | Prompt Groq avec instruction multilangue |
| Fichier trop grand (>20MB) | Bloque a l'upload |
| HEIC (iPhone) | Conversion auto vers JPEG via sharp |

## 7. Logs Extraction

Chaque tentative d'extraction est loguee dans `extraction_logs`:
- document_id
- modele utilise
- raw_response (JSON brut retourne)
- fields_extracted
- tokens_used
- latency_ms
- success (bool)
- error_message

## 8. Debug / Monitoring

```sql
-- Extraction rate
SELECT extraction_status, COUNT(*) FROM documents GROUP BY extraction_status;

-- Temps moyen par modele
SELECT extraction_model, AVG(latency_ms) FROM extraction_logs GROUP BY extraction_model;

-- Taux succes
SELECT (COUNT(*) FILTER (WHERE success) * 100.0 / COUNT(*)) as success_rate
FROM extraction_logs;
```

## 9. Dependances (package.json)

```json
{
  "dependencies": {
    "@vercel/blob": "^1.0.0",
    "groq-sdk": "^0.5.0",
    "sharp": "^0.33.0",
    "heic-convert": "^2.0.0",
    "pdf-parse": "^1.1.1"
  }
}
```
