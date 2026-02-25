// ============================================================
// Sovereign AI — Benefits Eligibility Policy Graph
// Seed Data: Income Support + Housing Assistance + Carer Payment
// ============================================================
// This Cypher script encodes structured government policy as a graph.
// The LLM never invents rules — it reads from this graph.
// All amounts in AUD, thresholds as of 2024 (indicative for PoC).
// ============================================================

// ── Cleanup (safe to run multiple times) ─────────────────────
MATCH (n) DETACH DELETE n;

// ── Legislation Nodes ─────────────────────────────────────────
CREATE (:Legislation {
  id: 'ssa-1991',
  name: 'Social Security Act 1991',
  year: 1991,
  jurisdiction: 'Commonwealth',
  url: 'https://www.legislation.gov.au/Details/C2024C00062'
});

CREATE (:Legislation {
  id: 'social-security-admin-1999',
  name: 'Social Security (Administration) Act 1999',
  year: 1999,
  jurisdiction: 'Commonwealth'
});

CREATE (:Legislation {
  id: 'housing-act-2018',
  name: 'National Housing and Homelessness Agreement 2018',
  year: 2018,
  jurisdiction: 'Commonwealth'
});

// ── Legal Clauses ──────────────────────────────────────────────
// Income Support clauses
CREATE (:LegalClause {
  id: 'ssa-s593',
  reference: 'Social Security Act 1991, Section 593',
  title: 'Qualification for jobseeker payment — general',
  summary: 'Person must be 22+ years or 18+ if exempt from youth allowance'
});
CREATE (:LegalClause {
  id: 'ssa-s601',
  reference: 'Social Security Act 1991, Section 601',
  title: 'Qualification — age requirement',
  summary: 'Age must be at or above the qualifying age and below pension age (67)'
});
CREATE (:LegalClause {
  id: 'ssa-s7',
  reference: 'Social Security Act 1991, Section 7',
  title: 'Australian resident — definition',
  summary: 'Must be an Australian resident as defined (citizen, permanent resident, or certain visa holders)'
});
CREATE (:LegalClause {
  id: 'ssa-s603',
  reference: 'Social Security Act 1991, Section 603',
  title: 'Income test for jobseeker payment',
  summary: 'Payment reduces when income exceeds the free area and stops at the cut-off'
});
CREATE (:LegalClause {
  id: 'ssa-s611',
  reference: 'Social Security Act 1991, Section 611',
  title: 'Assets test for social security payments',
  summary: 'Total assessable assets must not exceed the assets test limit'
});
CREATE (:LegalClause {
  id: 'ssa-s543aa',
  reference: 'Social Security Act 1991, Section 543AA',
  title: 'Mutual obligation requirements',
  summary: 'Must meet mutual obligation requirements unless exempt (medical certificate etc.)'
});

// Housing Assistance clauses
CREATE (:LegalClause {
  id: 'nhha-s4',
  reference: 'National Housing and Homelessness Agreement, Clause 4',
  title: 'Eligibility for housing assistance',
  summary: 'Applicable to low-income households unable to afford private rental market'
});

// Carer Payment clauses
CREATE (:LegalClause {
  id: 'ssa-s197a',
  reference: 'Social Security Act 1991, Section 197A',
  title: 'Qualification for Carer Payment',
  summary: 'Provides income support to people who are unable to work due to caring responsibilities'
});

// ── Legislation → Clause Relationships ────────────────────────
MATCH (leg:Legislation {id: 'ssa-1991'}),
      (c1:LegalClause {id: 'ssa-s593'}),
      (c2:LegalClause {id: 'ssa-s601'}),
      (c3:LegalClause {id: 'ssa-s7'}),
      (c4:LegalClause {id: 'ssa-s603'}),
      (c5:LegalClause {id: 'ssa-s611'}),
      (c6:LegalClause {id: 'ssa-s543aa'}),
      (c7:LegalClause {id: 'ssa-s197a'})
CREATE (c1)-[:PART_OF]->(leg),
       (c2)-[:PART_OF]->(leg),
       (c3)-[:PART_OF]->(leg),
       (c4)-[:PART_OF]->(leg),
       (c5)-[:PART_OF]->(leg),
       (c6)-[:PART_OF]->(leg),
       (c7)-[:PART_OF]->(leg);

MATCH (leg:Legislation {id: 'housing-act-2018'}),
      (c:LegalClause {id: 'nhha-s4'})
CREATE (c)-[:PART_OF]->(leg);

// ============================================================
// BENEFIT 1: Income Support (JobSeeker equivalent)
// ============================================================
CREATE (:Benefit {
  id: 'income-support',
  name: 'Income Support Payment',
  description: 'Financial assistance for people who are unemployed or unable to work full-time due to certain circumstances. Helps cover basic living expenses while you look for work or manage your situation.',
  category: 'employment_support',
  jurisdiction: 'National',
  weekly_max_rate: 383.35,
  fortnightly_max_rate: 766.70,
  currency: 'AUD',
  administered_by: 'Department of Social Services',
  website: 'https://www.servicesaustralia.gov.au/jobseeker-payment'
});

// Income Support — Eligibility Rules
CREATE (:EligibilityRule {
  id: 'is-age-rule',
  name: 'Age Requirement',
  description: 'Applicant must be within the qualifying age range for Income Support',
  mandatory: true,
  priority: 1
});

CREATE (:EligibilityRule {
  id: 'is-residency-rule',
  name: 'Residency Requirement',
  description: 'Applicant must be an Australian resident who has lived in Australia for at least 2 years',
  mandatory: true,
  priority: 2
});

CREATE (:EligibilityRule {
  id: 'is-income-rule',
  name: 'Income Test',
  description: 'Applicant income must be below the threshold. Payment reduces as income increases.',
  mandatory: true,
  priority: 3
});

CREATE (:EligibilityRule {
  id: 'is-assets-rule',
  name: 'Assets Test',
  description: 'Total assessable assets must be below the limit',
  mandatory: true,
  priority: 4
});

CREATE (:EligibilityRule {
  id: 'is-employment-rule',
  name: 'Employment Status',
  description: 'Must be unemployed or working less than 30 hours per week',
  mandatory: true,
  priority: 5
});

CREATE (:EligibilityRule {
  id: 'is-activity-rule',
  name: 'Activity / Mutual Obligation',
  description: 'Must be willing to meet mutual obligation requirements (actively seeking work, or have an approved exemption)',
  mandatory: true,
  priority: 6
});

// Income Support — Conditions
CREATE (:Condition {
  id: 'is-age-min',
  name: 'Minimum Age (22 years)',
  field: 'age',
  operator: 'GTE',
  value: 22,
  unit: 'years'
});

CREATE (:Condition {
  id: 'is-age-max',
  name: 'Below Pension Age (67 years)',
  field: 'age',
  operator: 'LTE',
  value: 67,
  unit: 'years'
});

CREATE (:Condition {
  id: 'is-residency-status',
  name: 'Australian Citizen or Permanent Resident',
  field: 'residency_status',
  operator: 'IN',
  value: 'citizen_or_pr',
  unit: ''
});

CREATE (:Condition {
  id: 'is-residency-duration',
  name: 'Minimum Residency Duration (24 months)',
  field: 'residency_months',
  operator: 'GTE',
  value: 24,
  unit: 'months'
});

CREATE (:Condition {
  id: 'is-income-single',
  name: 'Weekly Income Below Cut-off (Single)',
  field: 'weekly_income',
  operator: 'LTE',
  value: 1115.0,
  unit: 'AUD/week'
});

CREATE (:Condition {
  id: 'is-assets-single-homeowner',
  name: 'Assets Below Limit (Single Homeowner)',
  field: 'total_assets',
  operator: 'LTE',
  value: 280000,
  unit: 'AUD'
});

CREATE (:Condition {
  id: 'is-assets-single-non-homeowner',
  name: 'Assets Below Limit (Single Non-Homeowner)',
  field: 'total_assets',
  operator: 'LTE',
  value: 504500,
  unit: 'AUD'
});

CREATE (:Condition {
  id: 'is-employment-hours',
  name: 'Working Less Than 30 Hours Per Week',
  field: 'work_hours_per_week',
  operator: 'LTE',
  value: 30,
  unit: 'hours/week'
});

CREATE (:Condition {
  id: 'is-activity-seeking-work',
  name: 'Actively Seeking Employment',
  field: 'seeking_employment',
  operator: 'IS_TRUE',
  value: true,
  unit: ''
});

// Income Support — Exceptions
CREATE (:Exception {
  id: 'is-ex-medical',
  name: 'Medical Exemption (Mutual Obligation)',
  description: 'Temporary exemption from mutual obligation requirements if you have a medical certificate confirming you are temporarily unable to work',
  legal_reference: 'Social Security Act 1991, Section 543AB'
});

CREATE (:Exception {
  id: 'is-ex-carer',
  name: 'Carer Exemption',
  description: 'Reduced mutual obligation requirements if you are a principal carer of a child under 6',
  legal_reference: 'Social Security Act 1991, Section 543CA'
});

CREATE (:Exception {
  id: 'is-ex-age-18',
  name: 'Age Exception for 18-21 Year Olds',
  description: 'Those aged 18-21 may qualify if exempt from Youth Allowance (e.g. have a dependent child)',
  legal_reference: 'Social Security Act 1991, Section 593(1)(b)'
});

// Connect Income Support Benefit → Rules
MATCH (b:Benefit {id: 'income-support'}),
      (r1:EligibilityRule {id: 'is-age-rule'}),
      (r2:EligibilityRule {id: 'is-residency-rule'}),
      (r3:EligibilityRule {id: 'is-income-rule'}),
      (r4:EligibilityRule {id: 'is-assets-rule'}),
      (r5:EligibilityRule {id: 'is-employment-rule'}),
      (r6:EligibilityRule {id: 'is-activity-rule'})
CREATE (b)-[:HAS_RULE]->(r1),
       (b)-[:HAS_RULE]->(r2),
       (b)-[:HAS_RULE]->(r3),
       (b)-[:HAS_RULE]->(r4),
       (b)-[:HAS_RULE]->(r5),
       (b)-[:HAS_RULE]->(r6);

// Connect Rules → Conditions
MATCH (r:EligibilityRule {id: 'is-age-rule'}),
      (c1:Condition {id: 'is-age-min'}),
      (c2:Condition {id: 'is-age-max'})
CREATE (r)-[:HAS_CONDITION]->(c1),
       (r)-[:HAS_CONDITION]->(c2);

MATCH (r:EligibilityRule {id: 'is-residency-rule'}),
      (c1:Condition {id: 'is-residency-status'}),
      (c2:Condition {id: 'is-residency-duration'})
CREATE (r)-[:HAS_CONDITION]->(c1),
       (r)-[:HAS_CONDITION]->(c2);

MATCH (r:EligibilityRule {id: 'is-income-rule'}),
      (c:Condition {id: 'is-income-single'})
CREATE (r)-[:HAS_CONDITION]->(c);

MATCH (r:EligibilityRule {id: 'is-assets-rule'}),
      (c1:Condition {id: 'is-assets-single-homeowner'}),
      (c2:Condition {id: 'is-assets-single-non-homeowner'})
CREATE (r)-[:HAS_CONDITION]->(c1),
       (r)-[:HAS_CONDITION]->(c2);

MATCH (r:EligibilityRule {id: 'is-employment-rule'}),
      (c:Condition {id: 'is-employment-hours'})
CREATE (r)-[:HAS_CONDITION]->(c);

MATCH (r:EligibilityRule {id: 'is-activity-rule'}),
      (c:Condition {id: 'is-activity-seeking-work'})
CREATE (r)-[:HAS_CONDITION]->(c);

// Connect Conditions → Legal Clauses
MATCH (c:Condition {id: 'is-age-min'}), (lc:LegalClause {id: 'ssa-s601'})
CREATE (c)-[:DEFINED_BY]->(lc);
MATCH (c:Condition {id: 'is-age-max'}), (lc:LegalClause {id: 'ssa-s601'})
CREATE (c)-[:DEFINED_BY]->(lc);
MATCH (c:Condition {id: 'is-residency-status'}), (lc:LegalClause {id: 'ssa-s7'})
CREATE (c)-[:DEFINED_BY]->(lc);
MATCH (c:Condition {id: 'is-residency-duration'}), (lc:LegalClause {id: 'ssa-s7'})
CREATE (c)-[:DEFINED_BY]->(lc);
MATCH (c:Condition {id: 'is-income-single'}), (lc:LegalClause {id: 'ssa-s603'})
CREATE (c)-[:DEFINED_BY]->(lc);
MATCH (c:Condition {id: 'is-assets-single-homeowner'}), (lc:LegalClause {id: 'ssa-s611'})
CREATE (c)-[:DEFINED_BY]->(lc);
MATCH (c:Condition {id: 'is-assets-single-non-homeowner'}), (lc:LegalClause {id: 'ssa-s611'})
CREATE (c)-[:DEFINED_BY]->(lc);
MATCH (c:Condition {id: 'is-activity-seeking-work'}), (lc:LegalClause {id: 'ssa-s543aa'})
CREATE (c)-[:DEFINED_BY]->(lc);

// Connect Rules → Exceptions
MATCH (r:EligibilityRule {id: 'is-activity-rule'}),
      (e1:Exception {id: 'is-ex-medical'}),
      (e2:Exception {id: 'is-ex-carer'})
CREATE (r)-[:HAS_EXCEPTION]->(e1),
       (r)-[:HAS_EXCEPTION]->(e2);
MATCH (r:EligibilityRule {id: 'is-age-rule'}),
      (e:Exception {id: 'is-ex-age-18'})
CREATE (r)-[:HAS_EXCEPTION]->(e);

// ============================================================
// BENEFIT 2: Housing Assistance
// ============================================================
CREATE (:Benefit {
  id: 'housing-assistance',
  name: 'Commonwealth Rent Assistance',
  description: 'Financial help with rent for people who receive an income support payment and pay rent to a private landlord or community housing provider.',
  category: 'housing',
  jurisdiction: 'National',
  weekly_max_rate: 93.90,
  fortnightly_max_rate: 187.80,
  currency: 'AUD',
  administered_by: 'Services Australia',
  website: 'https://www.servicesaustralia.gov.au/rent-assistance'
});

CREATE (:EligibilityRule {
  id: 'ha-income-support-rule',
  name: 'Receiving Base Payment',
  description: 'Must be receiving an eligible income support payment (e.g., Income Support, Disability Support)',
  mandatory: true,
  priority: 1
});

CREATE (:EligibilityRule {
  id: 'ha-rent-rule',
  name: 'Rent Threshold',
  description: 'Must be paying rent above the minimum rent threshold',
  mandatory: true,
  priority: 2
});

CREATE (:EligibilityRule {
  id: 'ha-residence-type-rule',
  name: 'Private or Community Housing',
  description: 'Must be renting from a private landlord, real estate agent, or community housing provider (not public housing)',
  mandatory: true,
  priority: 3
});

CREATE (:Condition {
  id: 'ha-receives-base-payment',
  name: 'Receiving Eligible Income Support Payment',
  field: 'receives_income_support',
  operator: 'IS_TRUE',
  value: true,
  unit: ''
});

CREATE (:Condition {
  id: 'ha-min-rent-single',
  name: 'Weekly Rent Above Minimum (Single)',
  field: 'weekly_rent',
  operator: 'GTE',
  value: 133.60,
  unit: 'AUD/week'
});

CREATE (:Condition {
  id: 'ha-not-public-housing',
  name: 'Not in Public Housing',
  field: 'housing_type',
  operator: 'NOT_IN',
  value: 'public_housing',
  unit: ''
});

MATCH (b:Benefit {id: 'housing-assistance'}),
      (r1:EligibilityRule {id: 'ha-income-support-rule'}),
      (r2:EligibilityRule {id: 'ha-rent-rule'}),
      (r3:EligibilityRule {id: 'ha-residence-type-rule'})
CREATE (b)-[:HAS_RULE]->(r1),
       (b)-[:HAS_RULE]->(r2),
       (b)-[:HAS_RULE]->(r3);

MATCH (r:EligibilityRule {id: 'ha-income-support-rule'}),
      (c:Condition {id: 'ha-receives-base-payment'})
CREATE (r)-[:HAS_CONDITION]->(c);

MATCH (r:EligibilityRule {id: 'ha-rent-rule'}),
      (c:Condition {id: 'ha-min-rent-single'})
CREATE (r)-[:HAS_CONDITION]->(c);

MATCH (r:EligibilityRule {id: 'ha-residence-type-rule'}),
      (c:Condition {id: 'ha-not-public-housing'})
CREATE (r)-[:HAS_CONDITION]->(c);

MATCH (c:Condition {id: 'ha-receives-base-payment'}), (lc:LegalClause {id: 'nhha-s4'})
CREATE (c)-[:DEFINED_BY]->(lc);
MATCH (c:Condition {id: 'ha-min-rent-single'}), (lc:LegalClause {id: 'nhha-s4'})
CREATE (c)-[:DEFINED_BY]->(lc);
MATCH (c:Condition {id: 'ha-not-public-housing'}), (lc:LegalClause {id: 'nhha-s4'})
CREATE (c)-[:DEFINED_BY]->(lc);

// ============================================================
// BENEFIT 3: Carer Payment
// ============================================================
CREATE (:Benefit {
  id: 'carer-payment',
  name: 'Carer Payment',
  description: 'Income support for people who are unable to support themselves through substantial paid employment because they provide constant care for a person with a severe disability or medical condition, or for a frail aged person.',
  category: 'carer_support',
  jurisdiction: 'National',
  weekly_max_rate: 527.60,
  fortnightly_max_rate: 1055.20,
  currency: 'AUD',
  administered_by: 'Services Australia',
  website: 'https://www.servicesaustralia.gov.au/carer-payment'
});

CREATE (:EligibilityRule {
  id: 'cp-care-provision-rule',
  name: 'Providing Constant Care',
  description: 'Must provide constant care for a person with a severe disability or medical condition, or a frail aged person',
  mandatory: true,
  priority: 1
});

CREATE (:EligibilityRule {
  id: 'cp-age-rule',
  name: 'Carer Age Requirement',
  description: 'Carer must be within the qualifying age range',
  mandatory: true,
  priority: 2
});

CREATE (:EligibilityRule {
  id: 'cp-income-rule',
  name: 'Carer Income Test',
  description: 'Carer income must be below the threshold',
  mandatory: true,
  priority: 3
});

CREATE (:Condition {
  id: 'cp-provides-constant-care',
  name: 'Providing Constant Care',
  field: 'provides_constant_care',
  operator: 'IS_TRUE',
  value: true,
  unit: ''
});

CREATE (:Condition {
  id: 'cp-age-min',
  name: 'Minimum Age (18 years)',
  field: 'age',
  operator: 'GTE',
  value: 18,
  unit: 'years'
});

CREATE (:Condition {
  id: 'cp-income-limit',
  name: 'Weekly Income Below Cut-off',
  field: 'weekly_income',
  operator: 'LTE',
  value: 1115.0,
  unit: 'AUD/week'
});

MATCH (b:Benefit {id: 'carer-payment'}),
      (r1:EligibilityRule {id: 'cp-care-provision-rule'}),
      (r2:EligibilityRule {id: 'cp-age-rule'}),
      (r3:EligibilityRule {id: 'cp-income-rule'})
CREATE (b)-[:HAS_RULE]->(r1),
       (b)-[:HAS_RULE]->(r2),
       (b)-[:HAS_RULE]->(r3);

MATCH (r:EligibilityRule {id: 'cp-care-provision-rule'}),
      (c:Condition {id: 'cp-provides-constant-care'})
CREATE (r)-[:HAS_CONDITION]->(c);

MATCH (r:EligibilityRule {id: 'cp-age-rule'}),
      (c:Condition {id: 'cp-age-min'})
CREATE (r)-[:HAS_CONDITION]->(c);

MATCH (r:EligibilityRule {id: 'cp-income-rule'}),
      (c:Condition {id: 'cp-income-limit'})
CREATE (r)-[:HAS_CONDITION]->(c);

MATCH (c:Condition {id: 'cp-provides-constant-care'}), (lc:LegalClause {id: 'ssa-s197a'})
CREATE (c)-[:DEFINED_BY]->(lc);
MATCH (c:Condition {id: 'cp-age-min'}), (lc:LegalClause {id: 'ssa-s197a'})
CREATE (c)-[:DEFINED_BY]->(lc);
MATCH (c:Condition {id: 'cp-income-limit'}), (lc:LegalClause {id: 'ssa-s603'})
CREATE (c)-[:DEFINED_BY]->(lc);

// ── Verification Query (run to confirm) ───────────────────────
// MATCH (b:Benefit) RETURN b.id, b.name, b.weekly_max_rate;
// MATCH (b:Benefit)-[:HAS_RULE]->(r:EligibilityRule)-[:HAS_CONDITION]->(c:Condition)
//       -[:DEFINED_BY]->(lc:LegalClause)-[:PART_OF]->(leg:Legislation)
// RETURN b.name, r.name, c.name, lc.reference, leg.name;

RETURN 'Sovereign AI Policy Graph seeded successfully' AS status;
