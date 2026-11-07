"""Invented 14-entry source files; no personal data or source-file values."""
from qa_pending_basis_fixtures import source18

PHRASE='Nutrientes expresados por la porción total declarada, sin escalar en la importación.'
SCENARIOS=('clean','conflict','unknown','qualifiers','invalid')


def source14(scenario='clean'):
    assert scenario in SCENARIOS
    document=source18();document['data']['name']='QA fictional 14 editorial strings'
    entries=document['data']['entries']=document['data']['entries'][:14]
    for i,entry in enumerate(entries):
        entry['name']=f'QA fictional string food {i+1:02}'
        entry['meal_type']='breakfast' if i<4 else 'lunch' if i<8 else 'snack' if i<11 else 'dinner'
        entry['declaration']['provenance']['basis_interpretation']=PHRASE
        if scenario=='qualifiers':
            vector=entry['declaration']['nutrients'];vector['energy']['value']='0'
            vector['vitamin_d'].update(state='unknown',value=None)
            vector['iron'].update(state='trace',value=None)
            vector['zinc'].update(state='below_limit',value=None,limit='0.1')
    if scenario=='conflict':entries[-1]['declaration']['provenance']['basis_interpretation']='Los nutrientes no corresponden a la porción consumida.'
    if scenario=='unknown':entries[-1]['declaration']['provenance']['basis_interpretation']='<script>throw new Error("QA untrusted editorial text")</script>'
    if scenario=='invalid':entries[-1]['declaration']['provenance']['basis_interpretation']=False
    return document
