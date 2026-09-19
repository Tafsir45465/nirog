#!/usr/bin/env python3
"""Simple test runner that uses venv Python."""
import sys
import os
import subprocess

# Path to venv python
venv_python = "/sessions/sweet-hopeful-cannon/mnt/nirog/venv/Scripts/python.exe"

# Set environment
env = os.environ.copy()
env['PYTHONPATH'] = '/sessions/sweet-hopeful-cannon/mnt/nirog'
env['FLASK_ENV'] = 'testing'

if __name__ == '__main__':
    # Run unittest with venv python
    result = subprocess.run(
        [venv_python, '-m', 'unittest', 'discover', 'tests', '-p', '*_unittest.py', '-v'],
        cwd='/sessions/sweet-hopeful-cannon/mnt/nirog',
        env=env,
        capture_output=False
    )
    sys.exit(result.returncode)
