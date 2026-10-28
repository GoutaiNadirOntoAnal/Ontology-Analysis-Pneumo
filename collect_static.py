import os
import sys

PROJECT = "/home/ontolo54/mypfe1"

os.chdir(PROJECT)
sys.path.insert(0, PROJECT)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mypfe.settings")

from django.core.management import execute_from_command_line

execute_from_command_line([
    "manage.py",
    "collectstatic",
    "--noinput",
    "--clear"
])

print("STATIC OK")