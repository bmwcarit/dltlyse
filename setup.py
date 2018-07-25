#!/usr/bin/env python
"""Setup of DLTlyse"""

import os
import subprocess

from setuptools import setup, find_packages

__version__ = "1.0.0"

# https://pypi.python.org/pypi?%3Aaction=list_classifiers
CLASSIFIERS = [
    "Development Status :: 5 - Production/Stable",
    "License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)",
    "Operating System :: OS Independent",
    "Programming Language :: Python",
    "Topic :: Software Development :: Testing"
]

extra = {}
extra["install_requires"] = open("requirements.txt").read().splitlines()

try:
    version_git = os.getenv("GITPKGVTAG", None) or subprocess.check_output(["git", "rev-parse",
                                                                            "--short", "HEAD"]).rstrip()
except (subprocess.CalledProcessError, OSError):
    version_git = "unknown"
pkg_version = "{}+{}".format(__version__, version_git)


setup(
    name="dltlyse",
    version=pkg_version,
    description="DLT trace file analyser for the BMW head unit platform",
    long_description=open("README.md").read(),
    author="BMW Car IT",
    license="MPL 2.0",
    url="https://github.com/bmwcarit/dltlyse",
    keywords="dltlyse DLT trace analyse analyser testing testautomation test framework",
    platforms="any",
    classifiers=CLASSIFIERS,
    zip_safe=False,
    packages=find_packages(exclude=["tests", "tests.*"]),
    tests_require=["coverage"],
    entry_points={
        "console_scripts": [
            "dltlyse = dltlyse.run_dltlyse:main",
        ]
        },
    **extra
)
