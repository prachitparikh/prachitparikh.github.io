"""Build Tableau-ready CSVs from Prachit's three portfolio repos.

Sources (cloned to /tmp/repos):
  billing-migration-reconciliation  -> d1_*  (migration go/no-go)
  ai-ticket-triage-evaluation       -> d2_*  (AI triage evaluation)
  RequirementsIQ                    -> d3_*  (AI-assisted requirements to UAT)
All three use the fictional client Northstar Systems; the runs and numbers are real outputs of the code.
"""
import json
import pathlib

import pandas as pd

R = pathlib.Path('/tmp/repos')
OUT = pathlib.Path('/home/claude/tableau/out')
OUT.mkdir(parents=True, exist_ok=True)

# ---------------- D1: billing migration ----------------
BM = R / 'billing-migration-reconciliation/results'
LEVELS = {
    'L1': ('1', 'L1 Record counts'),
    'L2': ('2', 'L2 Control totals'),
    'L3': ('3', 'L3 Field-level match'),
    'RI': ('4', 'RI Referential integrity'),
    'L4': ('5', 'L4 Finance sign-off'),
}
checks, bridge, fin = [], [], []
for run in ('mock1', 'mock2'):
    s = json.load(open(BM / run / 'summary.json'))
    label = s['label']
    c = pd.read_csv(BM / run / 'checks.csv')
    c.insert(0, 'run', label)
    c.insert(1, 'run_date', s['run_date'])
    c.insert(2, 'migration_build', s['migration_build'])
    c['level_order'] = c['level'].map(lambda x: LEVELS[x][0])
    c['level_name'] = c['level'].map(lambda x: LEVELS[x][1])
    c['result'] = c['result'].str.replace('_', ' ').str.upper()
    checks.append(c)

    b = pd.read_csv(BM / run / 'l1_bridge.csv')
    stages = [
        ('1', 'Legacy source rows', 'source_rows'),
        ('2', 'Merged duplicates', 'merged'),
        ('3', 'Out of scope', 'out_of_scope'),
        ('4', 'Expected rejects', 'expected_rejects'),
        ('5', 'Expected loads', 'expected_loads'),
        ('6', 'Actual loads', 'actual_loads'),
        ('7', 'Missing in target', 'missing_in_target'),
        ('8', 'Loaded but not expected', 'not_expected'),
        ('9', 'Loaded twice', 'loaded_twice'),
    ]
    for _, row in b.iterrows():
        for order, name, col in stages:
            bridge.append({'run': label, 'entity': row['entity'], 'stage_order': int(order),
                           'stage': name, 'records': int(row[col]),
                           'bridge_balances': 'Balances' if row['bridge_balances'] == 1 else 'Does not balance'})

    f = pd.read_csv(BM / run / 'l4_finance.csv')
    f = f[f['check_id'].isin(['RC-L4-01', 'RC-L4-02', 'RC-L4-04', 'RC-L4-05'])].copy()
    f.insert(0, 'run', label)
    f['currency'] = f['dimension'].str.split(' ').str[0].str.split('/').str[0]
    fin.append(f)

pd.concat(checks).to_csv(OUT / 'd1_checks.csv', index=False)
pd.DataFrame(bridge).to_csv(OUT / 'd1_bridge.csv', index=False)
pd.concat(fin).rename(columns={'expected': 'expected_amount', 'actual': 'actual_amount', 'diff': 'difference'}) \
    .drop(columns=['unit']).to_csv(OUT / 'd1_finance.csv', index=False)
dq = pd.read_csv(BM / 'profiling/dq_results.csv')
dq['fail_rate'] = (dq['rows_failing'] / dq['rows_checked']).round(4)
dq.to_csv(OUT / 'd1_data_quality.csv', index=False)

# ---------------- D2: AI ticket triage ----------------
TT = R / 'ai-ticket-triage-evaluation/results'
METHOD = {
    'rules': ('1', "Today's routing rules"),
    'ml': ('2', 'In-house text model'),
    'llm_claude-haiku-5-5': ('3', 'Claude Haiku'),
    'llm_claude-sonnet-5-5': ('4', 'Claude Sonnet'),
}
comp = pd.read_csv(TT / 'comparison_test.csv')
LABELS = {
    'team_accuracy': ('Sent to the right team', 1),
    'category_accuracy': ('Right category', 1),
    'priority_accuracy': ('Right priority', 1),
    'all_three_right': ('Category, team and priority all right', 1),
    'category_macro_f1': ('Category macro F1', 1),
    'p1_recall': ('P1 tickets caught (recall)', 1),
    'p1_precision': ('P1 precision', 1),
    'security_to_trust': ('Security tickets sent to Trust', 1),
    'mixed_all_three_right': ('Mixed-intent tickets all right', 1),
    'other_language_all_three_right': ('Non-English tickets all right', 1),
    'false_urgency_priority_right': ('False urgency, priority right', 1),
}
rows = []
for _, r in comp.iterrows():
    for k, (lab, hib) in LABELS.items():
        rows.append({'method_order': int(METHOD[r['method']][0]), 'method': METHOD[r['method']][1],
                     'metric_key': k, 'metric': lab, 'value': float(r[k])})
    for k, lab in [('p1_rated_p3_or_lower', 'P1 tickets rated P3 or lower'),
                   ('under_prioritised', 'Tickets under-prioritised'),
                   ('injection_followed', 'Prompt-injection tickets that changed routing')]:
        rows.append({'method_order': int(METHOD[r['method']][0]), 'method': METHOD[r['method']][1],
                     'metric_key': k, 'metric': lab, 'value': float(r[k])})
pd.DataFrame(rows).to_csv(OUT / 'd2_metrics.csv', index=False)

acc = pd.read_csv(TT / 'acceptance_test.csv')
acc['method_order'] = acc['method'].map(lambda m: int(METHOD[m][0]))
acc['method'] = acc['method'].map(lambda m: METHOD[m][1])
acc['pass'] = acc['pass'].map({True: 'Pass', False: 'Fail', 'True': 'Pass', 'False': 'Fail'})
acc.to_csv(OUT / 'd2_acceptance.csv', index=False)

conf = []
for m, (o, lab) in METHOD.items():
    cm = pd.read_csv(TT / f'confusion/{m}__test__team.csv')
    for _, r in cm.iterrows():
        for pred in cm.columns[1:]:
            conf.append({'method_order': int(o), 'method': lab, 'actual_team': r['gold'].replace('_', ' ').title(),
                         'predicted_team': pred.replace('_', ' ').title(), 'tickets': int(r[pred])})
cdf = pd.DataFrame(conf)
cdf['correct'] = (cdf['actual_team'] == cdf['predicted_team']).map({True: 'Correct', False: 'Misrouted'})
cdf.to_csv(OUT / 'd2_confusion_team.csv', index=False)

bc = pd.read_csv(TT / 'business_case.csv')
bc['method'] = bc['method'].map(lambda m: METHOD[m][1])
bc.to_csv(OUT / 'd2_business_case.csv', index=False)

# ---------------- D3: RequirementsIQ ----------------
RQ = R / 'RequirementsIQ/powerbi/datasets'
proj = pd.read_csv(RQ / 'dim_project.csv')[['project_id', 'project_name']]


def tidy(df, etype, code, extra=None):
    cols = ['project_id', code, 'status', 'ai_generated', 'edited_after_ai', 'ai_confidence', 'priority',
            'created_at', 'first_submitted_at', 'first_decided_at'] + (extra or [])
    cols = [c for c in cols if c in df.columns]
    t = df[cols].rename(columns={code: 'code'}).copy()
    t.insert(1, 'artifact_type', etype)
    return t


req = pd.read_csv(RQ / 'fact_requirements.csv')
sto = pd.read_csv(RQ / 'fact_stories.csv')
tc = pd.read_csv(RQ / 'fact_test_cases.csv')
ac = pd.read_csv(RQ / 'fact_acceptance_criteria.csv')
ac['priority'] = None
art = pd.concat([
    tidy(req, 'Requirement', 'req_code', ['times_returned', 'finding_count']),
    tidy(sto, 'User story', 'story_code', ['story_points', 'ac_count']),
    tidy(ac, 'Acceptance criterion', 'ac_code', ['approved_test_count']),
    tidy(tc, 'UAT test case', 'tc_code', ['execution_status', 'uat_stage']),
])
order = {'Requirement': 1, 'User story': 2, 'Acceptance criterion': 3, 'UAT test case': 4}
art['artifact_order'] = art['artifact_type'].map(order)
art['origin'] = art.apply(lambda r: 'Written by a BA' if r['ai_generated'] == 0 else (
    'AI draft, edited by a BA' if r['edited_after_ai'] == 1 else 'AI draft, approved as written'), axis=1)
art = art.merge(proj, on='project_id')
art.to_csv(OUT / 'd3_artifacts.csv', index=False)

rc = pd.read_csv(RQ / 'fact_review_cycles.csv')
rc['entity_type'] = rc['entity_type'].str.replace('_', ' ').str.capitalize()
rc['waited_overnight'] = rc['waited_overnight'].map({1: 'Waited overnight', 0: 'Same day'})
rc = rc.merge(proj, on='project_id')
rc.to_csv(OUT / 'd3_review_cycles.csv', index=False)

fd = pd.read_csv(RQ / 'fact_findings.csv').merge(proj, on='project_id')
fd['origin'] = fd['ai_generated'].map({1: 'Found by AI review', 0: 'Found by a BA'})
fd.to_csv(OUT / 'd3_findings.csv', index=False)

for p in sorted(OUT.glob('*.csv')):
    n = sum(1 for _ in open(p)) - 1
    print(f'{p.name:28s} {n:6d} rows')
