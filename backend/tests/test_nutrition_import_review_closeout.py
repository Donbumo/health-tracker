"""Published review 5714776632: exact identity precedence and batch projections."""
import sys
from pathlib import Path
import pytest
from tests.conftest import login

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts/nutrition'))
from qa_review_closeout_cases import identity_case,grouping_case


@pytest.mark.parametrize('case',['ref','source_ids','missing_revision','missing_preparation','wrong_revision','wrong_preparation','name_only','manual','private'])
def test_explicit_identity_precedence_snapshots_and_restore(app,client,user,case):
    app.config['NUTRITION_INTELLIGENCE_ENABLED']=True;login(client)
    identity_case(user,client,case)


@pytest.mark.parametrize('size',[4,21,51])
def test_grouping_scope_order_history_and_roundtrip(app,client,user,size):
    app.config['NUTRITION_INTELLIGENCE_ENABLED']=True;login(client)
    grouping_case(user,client,size)
