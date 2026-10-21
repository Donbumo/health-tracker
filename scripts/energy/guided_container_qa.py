"""Offline C + protected-original regression in existing Python 3.12 local image."""
from pathlib import Path
import subprocess,sys
venv=Path('/tmp/energy-C-venv')
subprocess.run([sys.executable,'-m','venv','--system-site-packages',str(venv)],check=True)
python=str(venv/'bin/python')
subprocess.run([python,'-m','pip','install','--no-index','--find-links','/qa-wheels','pytest'],check=True)
subprocess.run([python,'-m','pytest','-q','--tb=short','-o','cache_dir=/tmp/energy-C-pytest-cache',
    'tests/test_energy_guided.py','tests/test_energy_provenance.py','--junitxml=/evidence/linux-focal.xml'],cwd='/qa-backend',check=True)
subprocess.run([python,'/qa-scripts/guided_mariadb_qa.py'],cwd='/qa-backend',check=True)
