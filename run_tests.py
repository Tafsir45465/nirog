#!/usr/bin/env python3
"""Simple test runner that bypasses venv import issues."""
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Set up minimal environment
os.environ.setdefault('FLASK_ENV', 'testing')

if __name__ == '__main__':
    import unittest

    # Discover and run tests
    loader = unittest.TestLoader()
    suite = loader.discover('tests', pattern='*_unittest.py')

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Exit with appropriate code
    sys.exit(0 if result.wasSuccessful() else 1)
