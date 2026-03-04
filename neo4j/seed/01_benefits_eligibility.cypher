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

// ============================================================
// BENEFIT 4: Disability Support Pension (DSP)
// ============================================================

// Legal Clauses (SSA 1991 — Part 2.3)
CREATE (:LegalClause {
  id: 'ssa-s94',
  reference: 'Social Security Act 1991, Section 94',
  title: 'Qualification for disability support pension',
  summary: 'Person must have a physical, intellectual or psychiatric condition that is likely to last at least 2 years and prevent working 15+ hours/week at award wages'
});
CREATE (:LegalClause {
  id: 'ssa-s95',
  reference: 'Social Security Act 1991, Section 95',
  title: 'Qualification — severe impairment',
  summary: 'Must have an impairment rating of 20 or more points under the Impairment Tables, or manifest eligibility'
});
CREATE (:LegalClause {
  id: 'ssa-s96',
  reference: 'Social Security Act 1991, Section 96',
  title: 'Disability Support Pension — residence requirements',
  summary: 'Must have been an Australian resident for at least 10 years (or qualify under an international social security agreement)'
});

MATCH (leg:Legislation {id: 'ssa-1991'}),
      (c1:LegalClause {id: 'ssa-s94'}),
      (c2:LegalClause {id: 'ssa-s95'}),
      (c3:LegalClause {id: 'ssa-s96'})
CREATE (c1)-[:PART_OF]->(leg),
       (c2)-[:PART_OF]->(leg),
       (c3)-[:PART_OF]->(leg);

CREATE (:Benefit {
  id: 'disability-support',
  name: 'Disability Support Pension',
  description: 'Income support for people with a permanent physical, intellectual or psychiatric condition that prevents them from working 15 or more hours per week. The condition must be expected to last at least 2 years.',
  category: 'disability_support',
  jurisdiction: 'National',
  weekly_max_rate: 548.35,
  fortnightly_max_rate: 1096.70,
  currency: 'AUD',
  administered_by: 'Services Australia',
  website: 'https://www.servicesaustralia.gov.au/disability-support-pension'
});

// DSP — Rules
CREATE (:EligibilityRule {
  id: 'dsp-age-rule',
  name: 'Age Requirement',
  description: 'Must be aged 16 years or older and below pension age (67)',
  mandatory: true,
  priority: 1
});
CREATE (:EligibilityRule {
  id: 'dsp-residency-rule',
  name: 'Residency Requirement',
  description: 'Must be an Australian resident who has lived in Australia for at least 10 years',
  mandatory: true,
  priority: 2
});
CREATE (:EligibilityRule {
  id: 'dsp-disability-rule',
  name: 'Permanent Disability Condition',
  description: 'Must have a permanent physical, intellectual or psychiatric condition likely to last at least 2 years',
  mandatory: true,
  priority: 3
});
CREATE (:EligibilityRule {
  id: 'dsp-work-capacity-rule',
  name: 'Unable to Work 15 Hours Per Week',
  description: 'The condition must prevent the person from working 15 or more hours per week at minimum wage',
  mandatory: true,
  priority: 4
});
CREATE (:EligibilityRule {
  id: 'dsp-income-rule',
  name: 'Income Test',
  description: 'Income must be below the threshold',
  mandatory: true,
  priority: 5
});
CREATE (:EligibilityRule {
  id: 'dsp-assets-rule',
  name: 'Assets Test',
  description: 'Total assessable assets must be below the limit',
  mandatory: true,
  priority: 6
});

// DSP — Conditions
CREATE (:Condition {
  id: 'dsp-age-min',
  name: 'Minimum Age (16 years)',
  field: 'age',
  operator: 'GTE',
  value: 16,
  unit: 'years'
});
CREATE (:Condition {
  id: 'dsp-age-max',
  name: 'Below Pension Age (67 years)',
  field: 'age',
  operator: 'LT',
  value: 67,
  unit: 'years'
});
CREATE (:Condition {
  id: 'dsp-residency-status',
  name: 'Australian Citizen or Permanent Resident',
  field: 'residency_status',
  operator: 'IN',
  value: 'citizen_or_pr',
  unit: ''
});
CREATE (:Condition {
  id: 'dsp-residency-duration',
  name: 'Minimum Residency Duration (120 months / 10 years)',
  field: 'residency_months',
  operator: 'GTE',
  value: 120,
  unit: 'months'
});
CREATE (:Condition {
  id: 'dsp-has-permanent-disability',
  name: 'Has Permanent Disability',
  field: 'has_permanent_disability',
  operator: 'IS_TRUE',
  value: true,
  unit: ''
});
CREATE (:Condition {
  id: 'dsp-work-capacity',
  name: 'Unable to Work 15+ Hours Per Week',
  field: 'work_capacity_hours_per_week',
  operator: 'LT',
  value: 15,
  unit: 'hours/week'
});
CREATE (:Condition {
  id: 'dsp-income-limit',
  name: 'Weekly Income Below Cut-off',
  field: 'weekly_income',
  operator: 'LTE',
  value: 1115.0,
  unit: 'AUD/week'
});
CREATE (:Condition {
  id: 'dsp-assets-homeowner',
  name: 'Assets Below Limit (Single Homeowner)',
  field: 'total_assets',
  operator: 'LTE',
  value: 280000,
  unit: 'AUD'
});
CREATE (:Condition {
  id: 'dsp-assets-non-homeowner',
  name: 'Assets Below Limit (Single Non-Homeowner)',
  field: 'total_assets',
  operator: 'LTE',
  value: 504500,
  unit: 'AUD'
});

// DSP — Exceptions
CREATE (:Exception {
  id: 'dsp-ex-manifest',
  name: 'Manifest Eligibility',
  description: 'Certain conditions qualify for DSP without needing to meet the full impairment table assessment: terminally ill, intellectual disability with IQ ≤54, legally blind, or receiving involuntary psychiatric treatment',
  legal_reference: 'Social Security Act 1991, Section 94A'
});
CREATE (:Exception {
  id: 'dsp-ex-agreement',
  name: 'International Social Security Agreement',
  description: 'Residency requirement may be waived for citizens of countries with which Australia has a social security agreement (e.g. UK, Italy, Germany, NZ)',
  legal_reference: 'Social Security Act 1991, Section 96(2)'
});

// Connect Benefit → Rules
MATCH (b:Benefit {id: 'disability-support'}),
      (r1:EligibilityRule {id: 'dsp-age-rule'}),
      (r2:EligibilityRule {id: 'dsp-residency-rule'}),
      (r3:EligibilityRule {id: 'dsp-disability-rule'}),
      (r4:EligibilityRule {id: 'dsp-work-capacity-rule'}),
      (r5:EligibilityRule {id: 'dsp-income-rule'}),
      (r6:EligibilityRule {id: 'dsp-assets-rule'})
CREATE (b)-[:HAS_RULE]->(r1),
       (b)-[:HAS_RULE]->(r2),
       (b)-[:HAS_RULE]->(r3),
       (b)-[:HAS_RULE]->(r4),
       (b)-[:HAS_RULE]->(r5),
       (b)-[:HAS_RULE]->(r6);

// Connect Rules → Conditions
MATCH (r:EligibilityRule {id: 'dsp-age-rule'}),
      (c1:Condition {id: 'dsp-age-min'}), (c2:Condition {id: 'dsp-age-max'})
CREATE (r)-[:HAS_CONDITION]->(c1), (r)-[:HAS_CONDITION]->(c2);

MATCH (r:EligibilityRule {id: 'dsp-residency-rule'}),
      (c1:Condition {id: 'dsp-residency-status'}), (c2:Condition {id: 'dsp-residency-duration'})
CREATE (r)-[:HAS_CONDITION]->(c1), (r)-[:HAS_CONDITION]->(c2);

MATCH (r:EligibilityRule {id: 'dsp-disability-rule'}),
      (c:Condition {id: 'dsp-has-permanent-disability'})
CREATE (r)-[:HAS_CONDITION]->(c);

MATCH (r:EligibilityRule {id: 'dsp-work-capacity-rule'}),
      (c:Condition {id: 'dsp-work-capacity'})
CREATE (r)-[:HAS_CONDITION]->(c);

MATCH (r:EligibilityRule {id: 'dsp-income-rule'}),
      (c:Condition {id: 'dsp-income-limit'})
CREATE (r)-[:HAS_CONDITION]->(c);

MATCH (r:EligibilityRule {id: 'dsp-assets-rule'}),
      (c1:Condition {id: 'dsp-assets-homeowner'}), (c2:Condition {id: 'dsp-assets-non-homeowner'})
CREATE (r)-[:HAS_CONDITION]->(c1), (r)-[:HAS_CONDITION]->(c2);

// Connect Conditions → Legal Clauses
MATCH (c:Condition {id: 'dsp-age-min'}), (lc:LegalClause {id: 'ssa-s94'})
CREATE (c)-[:DEFINED_BY]->(lc);
MATCH (c:Condition {id: 'dsp-age-max'}), (lc:LegalClause {id: 'ssa-s94'})
CREATE (c)-[:DEFINED_BY]->(lc);
MATCH (c:Condition {id: 'dsp-residency-status'}), (lc:LegalClause {id: 'ssa-s96'})
CREATE (c)-[:DEFINED_BY]->(lc);
MATCH (c:Condition {id: 'dsp-residency-duration'}), (lc:LegalClause {id: 'ssa-s96'})
CREATE (c)-[:DEFINED_BY]->(lc);
MATCH (c:Condition {id: 'dsp-has-permanent-disability'}), (lc:LegalClause {id: 'ssa-s94'})
CREATE (c)-[:DEFINED_BY]->(lc);
MATCH (c:Condition {id: 'dsp-work-capacity'}), (lc:LegalClause {id: 'ssa-s95'})
CREATE (c)-[:DEFINED_BY]->(lc);
MATCH (c:Condition {id: 'dsp-income-limit'}), (lc:LegalClause {id: 'ssa-s603'})
CREATE (c)-[:DEFINED_BY]->(lc);
MATCH (c:Condition {id: 'dsp-assets-homeowner'}), (lc:LegalClause {id: 'ssa-s611'})
CREATE (c)-[:DEFINED_BY]->(lc);
MATCH (c:Condition {id: 'dsp-assets-non-homeowner'}), (lc:LegalClause {id: 'ssa-s611'})
CREATE (c)-[:DEFINED_BY]->(lc);

// Connect Rules → Exceptions
MATCH (r:EligibilityRule {id: 'dsp-disability-rule'}),
      (e:Exception {id: 'dsp-ex-manifest'})
CREATE (r)-[:HAS_EXCEPTION]->(e);
MATCH (r:EligibilityRule {id: 'dsp-residency-rule'}),
      (e:Exception {id: 'dsp-ex-agreement'})
CREATE (r)-[:HAS_EXCEPTION]->(e);

// ============================================================
// BENEFIT 5: Age Pension
// ============================================================

// Legal Clauses (SSA 1991 — Part 2.2)
CREATE (:LegalClause {
  id: 'ssa-s43',
  reference: 'Social Security Act 1991, Section 43',
  title: 'Qualification for age pension',
  summary: 'Must have reached pension age (67), be an Australian resident, and meet income and assets tests'
});
CREATE (:LegalClause {
  id: 'ssa-s43a',
  reference: 'Social Security Act 1991, Section 43A',
  title: 'Age pension — residence requirement',
  summary: 'Must have been an Australian resident for at least 10 years, including at least 5 years continuous residence'
});
CREATE (:LegalClause {
  id: 'ssa-s1064',
  reference: 'Social Security Act 1991, Section 1064',
  title: 'Age pension — income test',
  summary: 'Pension reduces by 50 cents for every dollar of income above the free area; cuts out at upper income threshold'
});
CREATE (:LegalClause {
  id: 'ssa-s1073',
  reference: 'Social Security Act 1991, Section 1073',
  title: 'Age pension — assets test',
  summary: 'Pension reduces by $3 per fortnight for every $1,000 of assets above the lower threshold; cuts out at upper assets threshold'
});

MATCH (leg:Legislation {id: 'ssa-1991'}),
      (c1:LegalClause {id: 'ssa-s43'}),
      (c2:LegalClause {id: 'ssa-s43a'}),
      (c3:LegalClause {id: 'ssa-s1064'}),
      (c4:LegalClause {id: 'ssa-s1073'})
CREATE (c1)-[:PART_OF]->(leg),
       (c2)-[:PART_OF]->(leg),
       (c3)-[:PART_OF]->(leg),
       (c4)-[:PART_OF]->(leg);

CREATE (:Benefit {
  id: 'age-pension',
  name: 'Age Pension',
  description: 'Income support for Australians who have reached pension age (67) and meet residence, income and assets tests. Provides a regular payment to help with living expenses in retirement.',
  category: 'aged_support',
  jurisdiction: 'National',
  weekly_max_rate: 558.15,
  fortnightly_max_rate: 1116.30,
  currency: 'AUD',
  administered_by: 'Services Australia',
  website: 'https://www.servicesaustralia.gov.au/age-pension'
});

// Age Pension — Rules
CREATE (:EligibilityRule {
  id: 'ap-age-rule',
  name: 'Pension Age Requirement',
  description: 'Must have reached pension age (67 years or older)',
  mandatory: true,
  priority: 1
});
CREATE (:EligibilityRule {
  id: 'ap-residency-rule',
  name: 'Residency Requirement',
  description: 'Must be an Australian resident who has lived in Australia for at least 10 years, with at least 5 continuous years',
  mandatory: true,
  priority: 2
});
CREATE (:EligibilityRule {
  id: 'ap-income-rule',
  name: 'Income Test',
  description: 'Income must be below the pension income cut-off threshold',
  mandatory: true,
  priority: 3
});
CREATE (:EligibilityRule {
  id: 'ap-assets-rule',
  name: 'Assets Test',
  description: 'Total assessable assets must be below the pension assets limit',
  mandatory: true,
  priority: 4
});

// Age Pension — Conditions
CREATE (:Condition {
  id: 'ap-age-min',
  name: 'Pension Age (67 years or older)',
  field: 'age',
  operator: 'GTE',
  value: 67,
  unit: 'years'
});
CREATE (:Condition {
  id: 'ap-residency-status',
  name: 'Australian Citizen or Permanent Resident',
  field: 'residency_status',
  operator: 'IN',
  value: 'citizen_or_pr',
  unit: ''
});
CREATE (:Condition {
  id: 'ap-residency-duration',
  name: 'Minimum Residency Duration (120 months / 10 years)',
  field: 'residency_months',
  operator: 'GTE',
  value: 120,
  unit: 'months'
});
CREATE (:Condition {
  id: 'ap-income-limit',
  name: 'Fortnightly Income Below Cut-off (Single)',
  field: 'weekly_income',
  operator: 'LTE',
  value: 1159.0,
  unit: 'AUD/week'
});
CREATE (:Condition {
  id: 'ap-assets-homeowner',
  name: 'Assets Below Limit (Single Homeowner)',
  field: 'total_assets',
  operator: 'LTE',
  value: 674000,
  unit: 'AUD'
});
CREATE (:Condition {
  id: 'ap-assets-non-homeowner',
  name: 'Assets Below Limit (Single Non-Homeowner)',
  field: 'total_assets',
  operator: 'LTE',
  value: 916500,
  unit: 'AUD'
});

// Age Pension — Exceptions
CREATE (:Exception {
  id: 'ap-ex-agreement',
  name: 'International Social Security Agreement',
  description: 'Residency requirements may be reduced or waived under an international social security agreement with Australia (UK, Italy, Greece, Germany, NZ, and others)',
  legal_reference: 'Social Security Act 1991, Section 43A(2)'
});
CREATE (:Exception {
  id: 'ap-ex-refugee',
  name: 'Refugee / Humanitarian Visa Holder',
  description: 'Some residency requirements are waived for refugee and humanitarian visa holders',
  legal_reference: 'Social Security Act 1991, Section 43A(3)'
});

// Connect Benefit → Rules
MATCH (b:Benefit {id: 'age-pension'}),
      (r1:EligibilityRule {id: 'ap-age-rule'}),
      (r2:EligibilityRule {id: 'ap-residency-rule'}),
      (r3:EligibilityRule {id: 'ap-income-rule'}),
      (r4:EligibilityRule {id: 'ap-assets-rule'})
CREATE (b)-[:HAS_RULE]->(r1),
       (b)-[:HAS_RULE]->(r2),
       (b)-[:HAS_RULE]->(r3),
       (b)-[:HAS_RULE]->(r4);

// Connect Rules → Conditions
MATCH (r:EligibilityRule {id: 'ap-age-rule'}),
      (c:Condition {id: 'ap-age-min'})
CREATE (r)-[:HAS_CONDITION]->(c);

MATCH (r:EligibilityRule {id: 'ap-residency-rule'}),
      (c1:Condition {id: 'ap-residency-status'}), (c2:Condition {id: 'ap-residency-duration'})
CREATE (r)-[:HAS_CONDITION]->(c1), (r)-[:HAS_CONDITION]->(c2);

MATCH (r:EligibilityRule {id: 'ap-income-rule'}),
      (c:Condition {id: 'ap-income-limit'})
CREATE (r)-[:HAS_CONDITION]->(c);

MATCH (r:EligibilityRule {id: 'ap-assets-rule'}),
      (c1:Condition {id: 'ap-assets-homeowner'}), (c2:Condition {id: 'ap-assets-non-homeowner'})
CREATE (r)-[:HAS_CONDITION]->(c1), (r)-[:HAS_CONDITION]->(c2);

// Connect Conditions → Legal Clauses
MATCH (c:Condition {id: 'ap-age-min'}), (lc:LegalClause {id: 'ssa-s43'})
CREATE (c)-[:DEFINED_BY]->(lc);
MATCH (c:Condition {id: 'ap-residency-status'}), (lc:LegalClause {id: 'ssa-s43a'})
CREATE (c)-[:DEFINED_BY]->(lc);
MATCH (c:Condition {id: 'ap-residency-duration'}), (lc:LegalClause {id: 'ssa-s43a'})
CREATE (c)-[:DEFINED_BY]->(lc);
MATCH (c:Condition {id: 'ap-income-limit'}), (lc:LegalClause {id: 'ssa-s1064'})
CREATE (c)-[:DEFINED_BY]->(lc);
MATCH (c:Condition {id: 'ap-assets-homeowner'}), (lc:LegalClause {id: 'ssa-s1073'})
CREATE (c)-[:DEFINED_BY]->(lc);
MATCH (c:Condition {id: 'ap-assets-non-homeowner'}), (lc:LegalClause {id: 'ssa-s1073'})
CREATE (c)-[:DEFINED_BY]->(lc);

// Connect Rules → Exceptions
MATCH (r:EligibilityRule {id: 'ap-residency-rule'}),
      (e1:Exception {id: 'ap-ex-agreement'}), (e2:Exception {id: 'ap-ex-refugee'})
CREATE (r)-[:HAS_EXCEPTION]->(e1), (r)-[:HAS_EXCEPTION]->(e2);

// ── Verification Query (run to confirm) ───────────────────────
// MATCH (b:Benefit) RETURN b.id, b.name, b.weekly_max_rate;
// MATCH (b:Benefit)-[:HAS_RULE]->(r:EligibilityRule)-[:HAS_CONDITION]->(c:Condition)
//       -[:DEFINED_BY]->(lc:LegalClause)-[:PART_OF]->(leg:Legislation)
// RETURN b.name, r.name, c.name, lc.reference, leg.name;

RETURN 'Sovereign AI Policy Graph seeded successfully (5 benefits)' AS status;
