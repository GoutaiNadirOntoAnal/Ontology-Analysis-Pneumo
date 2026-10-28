"""
Passenger WSGI entry point for cPanel.
Version safe: no heavy imports here.
"""

import os
import sys
import logging

PROJECT_ROOT = "/home/ontolo54/mypfe1"

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mypfe.settings")

logging.getLogger("PyRuSH").setLevel(logging.ERROR)
logging.getLogger("medspacy").setLevel(logging.ERROR)
logging.getLogger("spacy").setLevel(logging.ERROR)

from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()
