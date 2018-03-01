"""Install Dallinger as a command line utility."""

import os
from setuptools import setup
import shlex
from subprocess import check_output, CalledProcessError

try:
    GIT_HEAD_REV = check_output(shlex.split('git rev-parse HEAD')).strip()
    GIT_MASTER_REV = check_output(shlex.split('git rev-parse HEAD')).strip()
except CalledProcessError:
    BUILD_TAG = ''
else:
    BUILD_TAG = 'dev_{}'.format(GIT_HEAD_REV)

setup_args = dict(
    name='dallinger',
    packages=['dallinger'],
    version="3.4.1",
    description='Laboratory automation for the behavioral and social sciences',
    url='http://github.com/Dallinger/Dallinger',
    maintainer='Jordan Suchow',
    maintainer_email='suchow@berkeley.edu',
    license='MIT',
    keywords=['science', 'cultural evolution', 'experiments', 'psychology'],
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Science/Research',
        'Topic :: Scientific/Engineering',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 2.6',
        'Programming Language :: Python :: 2.7',
    ],
    include_package_data=True,
    zip_safe=False,
    entry_points={
        'console_scripts': [
            'dallinger = dallinger.command_line:dallinger',
        ],
        'dallinger.experiments': [],
    },
    extras_require={
        'data': [
            "networkx==1.11",
            "odo==0.5.0",
            "tablib==0.11.3"
        ],
    },
    options={'egg_info': {
        'tag_build': BUILD_TAG
        }
    },

)

# If not on Heroku, install setuptools-markdown.
try:
    os.environ["DYNO"]
except KeyError:
    setup_args.update({
        "setup_requires": ['setuptools-markdown==0.2'],
        "long_description_markdown_filename": 'README.md',
    })

# Read in requirements.txt for dependencies.
setup_args['install_requires'] = install_requires = []
setup_args['dependency_links'] = dependency_links = []
with open('requirements.txt') as f:
    for line in f.readlines():
        req = line.strip()
        if not req or req.startswith('#'):
            continue
        if req.startswith('-e '):
            dependency_links.append(req[3:])
        else:
            install_requires.append(req)

setup(**setup_args)
