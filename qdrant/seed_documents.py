"""
Sovereign Brain — Qdrant Policy Document Seeder
================================================
Seeds the vector database with authoritative policy documents.
These serve as the RAG knowledge base for grounding LLM responses.

Usage:
  python qdrant/seed_documents.py

Requires:
  pip install qdrant-client fastembed
"""

import os
import sys

from fastembed import TextEmbedding
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
COLLECTION_NAME = os.getenv("QDRANT_COLLECTION", "sovereign-policy-docs")
FASTEMBED_MODEL = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIM = 384

# ── Policy Documents ───────────────────────────────────────────────────────────
POLICY_DOCUMENTS = [
    # ── Income Support Documents ─────────────────────────────────────────
    {
        "id": 1,
        "title": "Income Support Payment — Eligibility Overview",
        "source": "Services Australia — JobSeeker Payment Guide",
        "benefit_ids": ["income-support"],
        "jurisdiction": "National",
        "document_type": "eligibility_guide",
        "effective_date": "2024-03-20",
        "content": """
Income Support Payment (JobSeeker Payment) — Eligibility

To receive Income Support, you must meet ALL of the following criteria:

AGE: You must be aged 22 years or over, and under 67 years (pension age).
Special exception: If you are 18–21 and have a dependent child, you may qualify.

RESIDENCY: You must be an Australian citizen, permanent resident, or hold certain eligible visas.
You must have lived in Australia for at least 2 years as a resident.

INCOME TEST:
- Single, no children: Payment reduces when fortnightly income exceeds $150.
  Cuts off entirely when income reaches approximately $2,230 per fortnight ($1,115/week).
- Couples: Combined income limits apply at higher thresholds.
- Income includes: wages, rental income, investments, overseas income.
- Excluded: some government payments, first $150 per fortnight of employment income.

ASSETS TEST (2024):
- Single homeowner: Assets below $280,000
- Single non-homeowner: Assets below $504,500
- Couple homeowner: Assets below $419,000
- Couple non-homeowner: Assets below $643,500
- Assets include: bank accounts, shares, cars, property (excluding your home if homeowner)

EMPLOYMENT STATUS:
- Must be unemployed, or working less than 30 hours per week
- Includes part-time, casual, and seasonal workers below the hours threshold

MUTUAL OBLIGATION:
- Must be actively looking for work (minimum 15 job applications/month)
- Must attend appointments with your employment service provider
- Exemptions exist for: medical conditions (with certificate), principal carers of young children
""",
    },
    {
        "id": 2,
        "title": "Income Support — Payment Rates 2024",
        "source": "Services Australia — Payment Rates Guide March 2024",
        "benefit_ids": ["income-support"],
        "jurisdiction": "National",
        "document_type": "rate_schedule",
        "effective_date": "2024-03-20",
        "content": """
Income Support Payment Rates — Effective 20 March 2024

FORTNIGHTLY RATES (base rates, before income testing):

Single, no children:
  Maximum fortnightly rate: $766.70 ($383.35/week)

Single, 60+ and have been on payment 9+ months, no children:
  Maximum fortnightly rate: $816.90 ($408.45/week)

Single, principal carer:
  Maximum fortnightly rate: $882.40 ($441.20/week)

Couple, each partner:
  Maximum fortnightly rate: $706.50 ($353.25/week)

INCOME REDUCTION RULES:
- Income free area: $150 per fortnight (no reduction up to this amount)
- Above $150: payment reduces by 50 cents for each dollar earned
- Above $256 (part-time): payment reduces by 60 cents for each dollar
- Payment cuts out completely at approximately $2,230 per fortnight (single)

ENERGY SUPPLEMENT (add-on):
  Single: +$14.10/fortnight
  Couples: +$10.60/fortnight each

Note: Rates indexed to CPI annually. Confirm current rates at servicesaustralia.gov.au
""",
    },
    {
        "id": 3,
        "title": "Income Support — Mutual Obligation Requirements",
        "source": "Services Australia — Mutual Obligation Guide",
        "benefit_ids": ["income-support"],
        "jurisdiction": "National",
        "document_type": "obligations_guide",
        "effective_date": "2024-01-01",
        "content": """
Mutual Obligation Requirements for Income Support

You must meet mutual obligation requirements to continue receiving payment.

WHAT YOU MUST DO (typical requirements):
- Apply for at least 15 jobs per month via your online account
- Attend appointments with your employment services provider (e.g., jobactive, Workforce Australia)
- Participate in activities as directed (training, work experience, volunteering)
- Report any changes to your circumstances within 14 days

EXEMPTIONS — You may be exempt from some or all requirements if:
1. Medical: You have a temporary incapacity certified by a doctor (medical certificate required)
2. Domestic violence: You are experiencing or recovering from domestic violence
3. Carer: You are a principal carer of a child under 6 years old (reduced requirements)
4. Homelessness: You are experiencing homelessness (temporary exemption)
5. Bereavement: Recently bereaved (temporary exemption)

PENALTIES for non-compliance:
- First failure: Warning
- Subsequent failures: Temporary payment suspension
- Serious failure: 4-week payment penalty

JOB SEARCH EVIDENCE:
- Record all job applications in your online account
- Keep records (emails, confirmation numbers) in case of audit
""",
    },
    # ── Housing Assistance Documents ──────────────────────────────────────
    {
        "id": 4,
        "title": "Commonwealth Rent Assistance — Eligibility and Rates",
        "source": "Services Australia — Rent Assistance Guide",
        "benefit_ids": ["housing-assistance", "income-support"],
        "jurisdiction": "National",
        "document_type": "eligibility_guide",
        "effective_date": "2024-03-20",
        "content": """
Commonwealth Rent Assistance (CRA) — Eligibility and Rates

CRA is an additional payment on top of your income support payment to help cover rent costs.

WHO IS ELIGIBLE:
You must:
1. Receive an eligible income support payment (Income Support, Disability Support, Age Pension, etc.)
2. Pay rent above the minimum rent threshold
3. NOT be living in public housing (must be private or community housing)
4. Be renting from a private landlord, real estate agent, or community housing provider

MINIMUM RENT THRESHOLDS (2024) — you must pay at least this much to receive CRA:
- Single, no children: $133.60/fortnight ($66.80/week)
- Single, with children: $110.20/fortnight
- Couple, no children: $217.60/fortnight
- Couple, with children: $175.64/fortnight

MAXIMUM RATES (2024):
- Single, no children: $187.80/fortnight ($93.90/week)
- Single, with children: $221.82/fortnight
- Couple, no children: $177.32/fortnight
- Couple, with children: $221.82/fortnight

HOW CRA IS CALCULATED:
CRA = (Rent Paid − Rent Threshold) × 75¢ per dollar, up to the maximum rate.

Example:
- Single person pays $400/fortnight rent
- Rent threshold = $133.60
- Excess rent = $400 - $133.60 = $266.40
- CRA = $266.40 × 0.75 = $199.80 → capped at maximum $187.80/fortnight
""",
    },
    # ── Carer Payment Documents ───────────────────────────────────────────
    {
        "id": 5,
        "title": "Carer Payment — Eligibility Criteria",
        "source": "Services Australia — Carer Payment Guide",
        "benefit_ids": ["carer-payment"],
        "jurisdiction": "National",
        "document_type": "eligibility_guide",
        "effective_date": "2024-01-01",
        "content": """
Carer Payment — Eligibility

Carer Payment provides income support to people who cannot support themselves
through employment because they are providing constant care.

WHO QUALIFIES:

THE CARER must:
- Be 18 years or older
- Be providing constant care (daily personal care activities) to the care receiver
- Meet the income and assets tests
- Not be working more than 25 hours/week (employment exemption available)
- Be an Australian citizen, permanent resident, or eligible visa holder

THE CARE RECEIVER must have:
- A severe disability, severe medical condition, or be frail aged (80+)
- An Adult Disability Assessment Tool (ADAT) score of 30+ (or ADAT THP of 12+)
- OR be a child under 16 who requires significantly more care than other children their age

INCOME TEST (Carer):
- Single carer: Must earn below ~$2,230 per fortnight ($1,115/week)
- Income from the care receiver is NOT included in the carer's income test

ASSETS TEST: Same thresholds as Income Support

PAYMENT RATE (2024):
- Single: $1,055.20 per fortnight ($527.60/week)
- Couple: $794.80 each per fortnight ($397.40/week each)

CARER ALLOWANCE (separate payment):
In addition to Carer Payment, you may also receive Carer Allowance of $153.50/fortnight.
""",
    },
    # ── Disability Support Pension Documents ─────────────────────────────
    {
        "id": 8,
        "title": "Disability Support Pension — Eligibility Criteria",
        "source": "Services Australia — DSP Eligibility Guide",
        "benefit_ids": ["disability-support"],
        "jurisdiction": "National",
        "document_type": "eligibility_guide",
        "effective_date": "2024-03-20",
        "content": """
Disability Support Pension (DSP) — Eligibility

DSP provides income support for people with a permanent physical, intellectual or
psychiatric condition that prevents them from working 15 or more hours per week.

WHO QUALIFIES — THE PERSON must:

1. AGE: Be aged 16 years or older and below pension age (67).

2. RESIDENCY: Be an Australian citizen, permanent resident, or eligible visa holder
   AND have lived in Australia for at least 10 years (120 months).
   - International social security agreements may reduce the residency requirement.

3. PERMANENT DISABILITY: Have a physical, intellectual or psychiatric condition that:
   - Is fully diagnosed, treated and stabilised
   - Is likely to persist for at least 2 years
   - Causes an impairment rating of 20 points or more under the Impairment Tables
   OR have manifest eligibility (terminal illness, IQ ≤54, legally blind, or
   receiving involuntary psychiatric treatment).

4. WORK CAPACITY: The condition must prevent the person from working 15 or more
   hours per week at minimum wage in open employment, even with training or
   rehabilitation, for the next 2 years.

5. INCOME TEST: Weekly income below $1,115/week (single).
   Employment income of up to $180/fortnight is ignored (work incentive provision).

6. ASSETS TEST: Same thresholds as Income Support:
   - Single homeowner: below $280,000
   - Single non-homeowner: below $504,500

PAYMENT RATES (2024):
- Single, under 21, no children: $780.70/fortnight ($390.35/week)
- Single, 21 or older: $1,096.70/fortnight ($548.35/week)
- Couple (each): $826.70/fortnight ($413.35/week)

ASSESSMENTS REQUIRED:
- Job Capacity Assessment (JCA) with a trained assessor
- Impairment Table rating by a qualified health professional
- Treating specialist supporting evidence (GP/specialist report)
""",
    },
    {
        "id": 9,
        "title": "Disability Support Pension — Work Capacity and ADAT Assessment",
        "source": "Services Australia — DSP Assessment Guide",
        "benefit_ids": ["disability-support"],
        "jurisdiction": "National",
        "document_type": "assessment_guide",
        "effective_date": "2024-01-01",
        "content": """
DSP — Work Capacity Assessment and Impairment Tables

IMPAIRMENT TABLES:
DSP uses 15 Impairment Tables to rate the functional impact of a condition:
- Tables 1-4: Musculoskeletal (upper limb, lower limb, spinal)
- Tables 5-7: Neurological, sensory (vision, hearing)
- Table 8: Cardiovascular / respiratory
- Tables 9-11: Digestive, metabolic, reproductive
- Table 12: Mental health conditions
- Tables 13-15: Multiple conditions, fatigue, pain

Each table rates impairment from 0 to 30+ points.
MINIMUM 20 POINTS required to qualify for DSP (can be spread across multiple tables
using 5-point clusters from different tables).

MANIFEST ELIGIBILITY (no Impairment Table assessment required):
You may be granted DSP immediately if you have:
- A terminal illness (likely to die within 2 years)
- An intellectual disability with full-scale IQ of 54 or below
- Blindness (visual acuity <6/60 in better eye after correction)
- Receiving involuntary psychiatric treatment under a Mental Health Act

15-HOUR WORK CAPACITY RULE:
The condition must prevent working 15 or more hours per week at award wages.
This is assessed over the next 2 years, considering:
- Ability with any aids, equipment, or prostheses
- After reasonable training or rehabilitation

SUPPORTED EMPLOYMENT:
DSP recipients can work in Australian Disability Enterprises (ADEs) and sheltered
workshops without the hours counting against the 15-hour limit.

Note: Open employment of 30+ hours/week may trigger a DSP review.
""",
    },
    # ── Age Pension Documents ──────────────────────────────────────────────
    {
        "id": 10,
        "title": "Age Pension — Eligibility and Rates",
        "source": "Services Australia — Age Pension Eligibility Guide",
        "benefit_ids": ["age-pension"],
        "jurisdiction": "National",
        "document_type": "eligibility_guide",
        "effective_date": "2024-03-20",
        "content": """
Age Pension — Eligibility

The Age Pension provides income support to Australians who have reached pension age
and meet residency, income and assets requirements.

PENSION AGE: 67 years (for people born on or after 1 January 1957).

RESIDENCY REQUIREMENTS:
- Must be an Australian citizen, permanent resident, or eligible visa holder
- Must have lived in Australia for at least 10 years total
- At least 5 of those years must be continuous

INCOME TEST (2024):
- Single: Full pension if income ≤ $212/fortnight ($106/week)
  - Pension reduces by 50 cents per dollar above this
  - No pension if income ≥ $2,318.40/fortnight ($1,159/week)
- Couple: Full pension if combined income ≤ $372/fortnight
  - No pension if combined income ≥ $3,545.60/fortnight

ASSETS TEST (2024 — full cut-off thresholds):
- Single homeowner: No pension if assets ≥ $674,000
- Single non-homeowner: No pension if assets ≥ $916,500
- Couple homeowner: No pension if combined assets ≥ $1,012,500
- Couple non-homeowner: No pension if combined assets ≥ $1,255,000

Note: Your home is NOT counted in the assets test (if you live in it).
Assets include: bank accounts, shares, investment properties, vehicles, superannuation.

PAYMENT RATES (2024):
- Single: $1,116.30/fortnight ($558.15/week)
- Couple (each): $841.40/fortnight ($420.70/week)
- Pension Supplement: $81.60/fortnight (single) added on top
- Energy Supplement: $14.10/fortnight (single)

DEEMING:
Financial assets (bank accounts, shares, managed funds) are subject to deeming rates:
- First $60,400 (single): deemed to earn 0.25% p.a.
- Above $60,400 (single): deemed to earn 2.25% p.a.
""",
    },
    {
        "id": 11,
        "title": "Age Pension — Assets Test and Transitional Arrangements",
        "source": "Services Australia — Age Pension Assets Guide",
        "benefit_ids": ["age-pension"],
        "jurisdiction": "National",
        "document_type": "rate_schedule",
        "effective_date": "2024-03-20",
        "content": """
Age Pension Assets Test — Detailed Guide

ASSETS TEST THRESHOLDS (as at 20 March 2024):

FULL PENSION — assets must be BELOW:
- Single homeowner: $301,750
- Single non-homeowner: $543,750
- Couple homeowner: $451,500
- Couple non-homeowner: $693,500

PART PENSION — pension reduces by $3/fortnight per $1,000 above full pension threshold.
PENSION CUTS OUT ENTIRELY when assets reach:
- Single homeowner: $674,000
- Single non-homeowner: $916,500
- Couple homeowner: $1,012,500
- Couple non-homeowner: $1,255,000

WHAT IS COUNTED AS AN ASSET:
✓ Counted:
- Bank accounts and term deposits
- Shares, managed funds, ETFs
- Investment properties (not your primary home)
- Motor vehicles, boats, caravans
- Superannuation (if over pension age)
- Farm equipment, business assets
- Loans you have made to others

✗ NOT counted:
- Your principal home (primary residence)
- Funeral bonds up to $14,000
- Some family trusts (specialist advice required)

PROPERTY AND HOMEOWNER STATUS:
- You are a "homeowner" if you own or are paying off the home you live in.
- Granny flats and life interests may have special treatment.
- If you sell your home, proceeds are assessed for up to 12 months.

GIFTING RULES:
- You can gift up to $10,000/year (max $30,000 over 5 years) without it affecting your pension.
- Amounts above this are assessed as a "deprived asset" for 5 years.
""",
    },
    # ── Appeals and Review ────────────────────────────────────────────────
    {
        "id": 6,
        "title": "Appealing a Benefits Decision",
        "source": "Services Australia — Review and Appeal Guide",
        "benefit_ids": ["income-support", "housing-assistance", "carer-payment", "disability-support"],
        "jurisdiction": "National",
        "document_type": "appeal_guide",
        "effective_date": "2024-01-01",
        "content": """
How to Appeal a Centrelink/Services Australia Decision

If you disagree with a decision about your benefits, you have the right to appeal.

STEP 1 — Request an Internal Review (first 13 weeks):
- Call Services Australia: 132 300
- Ask for an Authorised Review Officer (ARO) review
- The ARO is independent from the original decision maker
- You can provide new information or documents at this stage
- Timeframe: Decision usually within 30–90 days

STEP 2 — Administrative Appeals Tribunal (AAT):
- If still unsatisfied after internal review
- Apply within 13 weeks of receiving the internal review decision
- Phone: 1800 228 333
- Online: aat.gov.au
- Free for most applicants
- More formal process with hearings

STEP 3 — Federal Court:
- Only for matters of law, not facts
- Legal advice strongly recommended

IMPORTANT RIGHTS:
- You can receive payment during an appeal in some circumstances
- Ask for a Debt Waiver if the decision relates to an overpayment you cannot repay
- Request a statement of reasons for any decision
- You can bring a support person to any appointment or hearing

Community Legal Centres can provide free advice on Centrelink matters.
National Welfare Rights Network: 1800 100 490
""",
    },
    # ── General Benefits Overview ─────────────────────────────────────────
    {
        "id": 7,
        "title": "Government Benefits Overview — Finding the Right Payment",
        "source": "Services Australia — Benefits Navigator Guide",
        "benefit_ids": ["income-support", "housing-assistance", "carer-payment", "disability-support", "age-pension", "family-payment"],
        "jurisdiction": "National",
        "document_type": "overview",
        "effective_date": "2024-01-01",
        "content": """
Government Benefits — Quick Reference Guide

EMPLOYMENT-RELATED:
- Income Support (JobSeeker): Unemployed or working under 30 hrs/week, aged 22–67
- Youth Allowance: Studying or job seeking, aged 16–24
- Austudy: Studying, aged 25+

DISABILITY AND HEALTH:
- Disability Support Pension (DSP): Permanent disability preventing work ≥ 15hrs/week
- Carer Payment: Unable to work due to providing constant care
- Carer Allowance: Additional support for carers ($153.50/fortnight)

HOUSING:
- Commonwealth Rent Assistance: Add-on for those paying private/community rent
- First Home Owner Grant: State-based assistance for first home buyers

FAMILY:
- Family Tax Benefit Part A: For families with dependent children (income tested)
- Family Tax Benefit Part B: Single income families or sole parents
- Parenting Payment: Principal carer of a young child

AGED:
- Age Pension: Men and women aged 67+, income and assets tested

HOW TO APPLY:
1. Create a myGov account (my.gov.au)
2. Link Services Australia to myGov
3. Use online claim forms or call 132 300
4. Provide identity documents, income/asset details

WAIT TIMES:
- Initial claims: 1–6 weeks depending on payment type
- Complex claims: May take longer
- Emergency payments available in hardship situations
""",
    },
]


def seed(host: str = QDRANT_HOST, port: int = QDRANT_PORT):
    print(f"Connecting to Qdrant at {host}:{port}...")
    client = QdrantClient(host=host, port=port)

    # Create or recreate collection
    try:
        client.delete_collection(COLLECTION_NAME)
        print(f"Deleted existing collection: {COLLECTION_NAME}")
    except Exception:
        pass

    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
    )
    print(f"Created collection: {COLLECTION_NAME}")

    # Load embedding model
    print(f"Loading embedding model: {FASTEMBED_MODEL}")
    embedder = TextEmbedding(model_name=FASTEMBED_MODEL)
    print("Embedding model loaded")

    # Embed and upsert documents
    points = []
    for doc in POLICY_DOCUMENTS:
        # Embed title + content for richer retrieval
        text_to_embed = f"{doc['title']}\n\n{doc['content']}"
        vector = list(embedder.embed([text_to_embed]))[0].tolist()

        payload = {k: v for k, v in doc.items() if k not in ("id",)}
        points.append(PointStruct(id=doc["id"], vector=vector, payload=payload))
        print(f"  ✅ Embedded: {doc['title']}")

    client.upsert(collection_name=COLLECTION_NAME, points=points)
    print(f"\n🎯 Seeded {len(points)} policy documents into Qdrant collection '{COLLECTION_NAME}'")
    print("RAG retrieval is ready.")


if __name__ == "__main__":
    host = sys.argv[1] if len(sys.argv) > 1 else QDRANT_HOST
    port = int(sys.argv[2]) if len(sys.argv) > 2 else QDRANT_PORT
    seed(host, port)
