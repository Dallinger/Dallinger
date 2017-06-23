"""Install Dallinger as a command line utility."""

import os
from setuptools import setup

setup_args = dict(
    name='dallinger',
    packages=['dallinger', 'demos'],
    version="3.0.1",
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
        'dallinger.experiments': [
            'Bartlett1932 = demos.bartlett1932.experiment:Bartlett1932',
        ],
    },
    extras_require={
        'data': [
            "odo==0.5.0",
            "tablib==0.11.3"
        ],
    }
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
