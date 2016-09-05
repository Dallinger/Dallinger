"""Install Wallace as a command line utility."""

import pypandoc
from setuptools import setup

long_description = pypandoc.convert('README.md', 'rst', format='markdown')
long_description = long_description.replace('\r', '')
with open('README.rst', 'w') as outfile:
    outfile.write(long_description)

setup_args = dict(
    name='wallace-platform',
    packages=['wallace'],
    version="1.0.0",
    description='Wallace, a platform for experimental cultural evolution',
    long_description=long_description,
    url='http://github.com/berkeley-cocosci/Wallace',
    author='Berkeley CoCoSci',
    author_email='wallace@cocosci.berkeley.edu',
    license='MIT',
    keywords=['science', 'cultural evolution', 'experiments', 'psychology'],
    classifiers=[],
    include_package_data=True,
    zip_safe=False,
    entry_points={
        'console_scripts': [
            'wallace = wallace.command_line:wallace',
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
