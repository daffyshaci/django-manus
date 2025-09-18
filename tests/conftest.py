# Ensure the project root is on sys.path and Django is initialized for tests
import os
import sys

ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Ensure DJANGO_SETTINGS_MODULE is set
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.django.local')

# Initialize Django before tests collection begins
try:
    import django
    from django.conf import settings
    if not settings.configured:
        django.setup()
    else:
        # Even if configured, ensure app registry is ready
        django.setup()
except Exception as e:
    # Fail fast with a clear message if Django cannot initialize
    raise RuntimeError(f"Failed to initialize Django for tests: {e}")