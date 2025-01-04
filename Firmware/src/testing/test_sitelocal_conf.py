"""
Tests the sitelocal_conf module
"""

import sys

# Make sure this works even when executing from the testing dir
sys.path.append(".")

import os
from sitelocal_conf import updateLocal


# The test config should not exist
if "my_conf.py" in os.listdir():
    raise RuntimeError("Can not test: my_cong.py file already exists.")
# Create it
# Not found, so we create it.
with open("my_conf.py", "w", encoding="utf-8") as cf:
    cf.write(
        "from sitelocal_conf import overrideLocal\n"
        + "FOO = 22\n"
        + "BAR = 'foobar'\n"
        + "JAZZY = None\n\n"
        + "# Override any site local values\n"
        + "overrideLocal(__name__, locals())"
    )


# And now import it
import my_conf

print("\n\nCurrent config:")
for n in dir(my_conf):
    if n.startswith("_"):
        continue
    print(f"{n} = {getattr(my_conf, n)}")
print("\n\n")

# Now we update some of the vars
my_conf.JAZZY = "Jazzy Jeff."
my_conf.FOO = (7, 9, {"a": "is A", "b": None, "c": 99})

# Update locals and store local file.
updateLocal(["JAZZY", "FOO"], my_conf)

# Now we delete my_conf so we can import it again
del my_conf

import my_conf


print("\n\nUpdatef config from site local:")
for n in dir(my_conf):
    if n.startswith("_"):
        continue
    print(f"{n} = {getattr(my_conf, n)}")

print("\n\nRemoving my_conf.py and my_conf_local.py...\n")

os.unlink("my_conf.py")
os.unlink("my_conf_local.py")
