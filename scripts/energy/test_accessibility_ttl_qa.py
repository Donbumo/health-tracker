"""The TTL probe must reject non-QA targets before constructing an HTTP client."""
import importlib.util
from pathlib import Path
import sqlite3
import sys

import pytest


@pytest.mark.parametrize('case', ['remote', 'userinfo', 'url_path', 'directory', 'filename', 'owners'])
def test_probe_refuses_unsafe_target_before_network(tmp_path, monkeypatch, case):
    spec = importlib.util.spec_from_file_location('energy_ttl_probe', Path(__file__).with_name('accessibility_ttl_qa.py'))
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    folder = tmp_path / ('not-a-QA-folder' if case == 'directory' else 'QA-energy-D-guard')
    folder.mkdir()
    database = folder / ('other.sqlite' if case == 'filename' else 'qa.sqlite')
    with sqlite3.connect(database) as con:
        con.execute('CREATE TABLE users (username TEXT)')
        con.execute('INSERT INTO users VALUES (?)', ('QA unexpected fixture',))
    url = {'remote':'http://example.invalid:1234', 'userinfo':'http://QA:QA@127.0.0.1:1234',
           'url_path':'http://127.0.0.1:1234/other'}.get(case, 'http://127.0.0.1:1234')
    network = []
    def forbidden_client(*args, **kwargs):
        network.append(True)
        raise RuntimeError('No HTTP client should be constructed')
    monkeypatch.setattr(probe, 'build_opener', forbidden_client)
    output = tmp_path / 'should-not-exist.json'
    monkeypatch.setattr(sys, 'argv', ['probe', '--url', url, '--database', str(database), '--output', str(output)])
    with pytest.raises(AssertionError):
        probe.main()
    assert network == [] and not output.exists()
