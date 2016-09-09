"""Install Dallinger as a command line utility."""

import pypandoc
from setuptools import setup

long_description = pypandoc.convert('README.md', 'rst', format='markdown')
long_description = long_description.replace('\r', '')
with open('README.rst', 'w') as outfile:
    outfile.write(long_description)

setup_args = dict(
    name='dallinger',
    packages=['dallinger'],
    version="2.0.1",
    description='Laboratory automation for the behavioral and social sciences',
    long_description=long_description,
    url='http://github.com/Dallinger/Dallinger',
    maintainer='Jordan Suchow',
    maintainer_email='suchow@berkeley.edu',
    license='MIT',
    keywords=['science', 'cultural evolution', 'experiments', 'psychology'],
    classifiers=[],
    include_package_data=True,
    zip_safe=False,
    entry_points={
        'console_scripts': [
            'dallinger = dallinger.command_line:dallinger',
        ],
    }
)

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
