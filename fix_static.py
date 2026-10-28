import os
import shutil
from django.core.management import execute_from_command_line

PROJECT = "/home/ontolo54/mypfe1"
SRC = "/home/ontolo54/mypfe1/staticfiles"
DST = "/home/ontolo54/public_html/static"

os.chdir(PROJECT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mypfe.settings")

execute_from_command_line(["manage.py", "collectstatic", "--noinput"])

if os.path.islink(DST) or os.path.isfile(DST):
    os.unlink(DST)
elif os.path.isdir(DST):
    shutil.rmtree(DST)

os.symlink(SRC, DST)

print("OK static link created")
print(DST, "->", SRC)