"""Real 15-minute HTTP expiry probe, only against the fictional local D fixture."""
import argparse
from datetime import datetime
import hashlib
import html
import json
from pathlib import Path
import re
import sqlite3
import time
from urllib.parse import urlsplit, urlencode
from urllib.request import Request, build_opener, HTTPCookieProcessor, HTTPRedirectHandler, ProxyHandler
from urllib.error import HTTPError
from http.cookiejar import CookieJar
from types import SimpleNamespace
import uuid
from zoneinfo import ZoneInfo


def hidden(text):
    result = {}
    for tag in re.findall(r'<input\b[^>]*>', text):
        attrs = {k: html.unescape(v) for k, v in re.findall(r'([\w_-]+)="([^"]*)"', tag)}
        if attrs.get('type') == 'hidden':
            result[attrs['name']] = attrs.get('value', '')
    return result


def snapshot(database):
    with sqlite3.connect(database.as_uri()+'?mode=ro', uri=True) as con:
        assert set(con.execute('SELECT username FROM users').fetchall()) == {('QA-energy-D',), ('QA-energy-D-other',)}
        result = {}
        names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in ('daily_energy', 'energy_days', 'energy_evidence_events', 'uploaded_files', 'import_runs'):
            assert table in names, table
            rows = con.execute(f'SELECT * FROM {table} ORDER BY id').fetchall()
            result[table] = {'rows': len(rows), 'digest': hashlib.sha256(json.dumps(rows, default=str).encode()).hexdigest()}
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    url = urlsplit(args.url)
    assert url.scheme == 'http' and url.hostname == '127.0.0.1' and url.port and not url.username and not url.password
    assert url.path in ('', '/') and not url.query and not url.fragment
    database = args.database.resolve()
    assert database.name == 'qa.sqlite' and database.parent.name.startswith('QA-energy-D-')
    snapshot(database)  # Refuse any non-fictional database before the first POST.
    base = args.url.rstrip('/')
    class LocalRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            assert newurl.startswith(base+'/')
            return super().redirect_request(req, fp, code, msg, headers, newurl)
    client = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()), LocalRedirect())
    def request(method, route, data=None, files=None):
        headers = {}
        if files:
            boundary = 'QA-TTL-'+uuid.uuid4().hex
            parts = []
            for key, value in (data or {}).items():
                parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
            for key, (name, raw_file, content_type) in files.items():
                parts.extend([f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"; filename="{name}"\r\nContent-Type: {content_type}\r\n\r\n'.encode(), raw_file, b'\r\n'])
            parts.append(f'--{boundary}--\r\n'.encode())
            body = b''.join(parts); headers['Content-Type'] = 'multipart/form-data; boundary='+boundary
        else:
            body = urlencode(data).encode() if data is not None else None
        req = Request(base+route, data=body, headers=headers, method=method)
        try:
            response = client.open(req, timeout=30)
        except HTTPError as exc:
            response = exc
        with response:
            assert response.geturl().startswith(base+'/')
            return SimpleNamespace(status_code=response.code, text=response.read().decode('utf-8'), url=response.geturl())
    start = request('GET', '/login')
    csrf = hidden(start.text)['csrf_token']
    auth = request('POST', '/login', data={'csrf_token':csrf, 'username':'QA-energy-D', 'password':'fictional-energy-D-password'})
    assert auth.status_code == 200
    identity = request('GET', '/energy?date=2040-02-03&period=7')
    assert identity.status_code == 200 and 'QA ficticia D' in identity.text and '2450' in identity.text
    before = snapshot(database)
    def advance(response, action, route='/energy/import', **extras):
        result = request('POST', route, data={**hidden(response.text), 'action':action, **extras})
        return result
    doc = {'schema_version':'1.0', 'record_type':'daily_energy', 'user_id':1, 'source_type':'uploaded',
           'data':{'date':'2040-05-01', 'source':'QA TTL ficticia', 'steps':0}}
    raw = json.dumps(doc).encode()
    first = request('POST', '/energy/import', data={'csrf_token':csrf,'action':'upload'}, files={'file':('QA-TTL.json',raw,'application/json')})
    assert first.status_code == 200
    second = advance(first, 'review'); assert second.status_code == 200
    final_import = advance(second, 'approve'); assert final_import.status_code == 200
    review = request('POST', '/energy/review', data={'csrf_token':csrf,'action':'review','date':'2040-02-03',
        'choice_total_calories':'manual','value_total_calories':'2460','choice_notes':'manual','value_notes':'QA TTL draft ficticio'})
    assert review.status_code == 200
    final_review = advance(review, 'approve', '/energy/review'); assert final_review.status_code == 200
    assert snapshot(database) == before
    report = {'scope':'real HTTP; fictional local D fixture only; no NAS', 'status':'RUNNING',
        'client_timezone':'America/Mexico_City', 'started_at':datetime.now(ZoneInfo('America/Mexico_City')).isoformat(),
        'method':'unmodified server clock, genuine server-issued tokens; wait >=903 seconds after both final pages',
        'preview_domain_and_files_unchanged':True, 'warning':{'step2':'caduca en 15 minutos' in first.text,
            'step3':'caduca en 15 minutos' in second.text, 'step4':'caduca en 15 minutos' in final_import.text},
        'security_modified':False, 'tokens_or_originals_in_report':False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    began = time.monotonic()
    print(json.dumps({'status':'RUNNING','method':'real 903-second expiry; no clock or security change'}),flush=True)
    while time.monotonic()-began < 903:
        time.sleep(min(30, 903-(time.monotonic()-began)))
    expired_import = advance(final_import, 'confirm', confirm='yes')
    expired_review = advance(final_review, 'confirm', '/energy/review', confirm='yes')
    elapsed = round(time.monotonic()-began,2)
    after = snapshot(database)
    fresh_review = request('GET','/energy/review?date=2040-02-03')
    fresh_import = request('POST','/energy/import',data={'csrf_token':csrf,'action':'upload'},files={'file':('QA-TTL.json',raw,'application/json')})
    report.update({'status':'COMPLETE','elapsed_seconds':elapsed,
        'finished_at':datetime.now(ZoneInfo('America/Mexico_City')).isoformat(),
        'expired_import':{'http':expired_import.status_code,'original_draft_retained':'envelope' in hidden(expired_import.text),
            'fresh_signed_token_issued':'review_token' in hidden(expired_import.text),'focused_error_markup':'role="alert" tabindex="-1" autofocus' in expired_import.text},
        'expired_review':{'http':expired_review.status_code,'manual_draft_retained':'QA TTL draft ficticio' in expired_review.text,
            'fresh_signed_token_issued':'review_token' in hidden(expired_review.text),'focused_error_markup':'role="alert" tabindex="-1" autofocus' in expired_review.text},
        'domain_and_file_metadata_unchanged':before==after,
        'recovery':{'fresh_import_preview_http':fresh_import.status_code,'fresh_review_http':fresh_review.status_code,
            'fresh_review_repopulates_prior_manual_draft':'QA TTL draft ficticio' in fresh_review.text,
            'requires':('import: reselect original and repeat preview/review/confirmation; decisions: '+
                ('review the preserved draft, reselect sources and repeat explicit review/confirmation' if 'QA TTL draft ficticio' in expired_review.text
                 else 'reopen day and re-enter choices/values, review and confirm'))},
        'security_gate':'PASS' if expired_import.status_code==expired_review.status_code==409 and before==after else 'FAIL',
        'timing_adjustment_controls':'none in current C; static warning only at step 4; no proactive expiry notice',
        'audible_expiry_notice':'NOT TESTED; no audio observation inferred from markup'})
    args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':report['status'],'security_gate':report['security_gate'],'elapsed_seconds':elapsed,
                      'import_http':expired_import.status_code,'review_http':expired_review.status_code,
                      'draft_preserved':report['expired_review']['manual_draft_retained']}),flush=True)
    assert report['security_gate']=='PASS'


if __name__ == '__main__':
    main()
