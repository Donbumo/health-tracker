"""Offline focal QA runner in an existing local Python 3.12 image, never NAS."""
from pathlib import Path
import subprocess,sys

venv=Path('/tmp/energy-B-venv')
subprocess.run([sys.executable,'-m','venv','--system-site-packages',str(venv)],check=True)
python=str(venv/'bin/python')
subprocess.run([python,'-m','pip','install','--no-index','--find-links','/qa-wheels','pytest'],check=True)
subprocess.run([python,'-m','pytest','-q','-o','cache_dir=/tmp/energy-B-pytest-cache','tests/test_energy_provenance.py',
    '--junitxml=/evidence/linux-focal.xml'],cwd='/qa-backend',check=True)
subprocess.run([python,'/qa-scripts/provenance_mariadb_qa.py'],cwd='/qa-backend',check=True)
