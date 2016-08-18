"""Install Wallace as a command line utility."""

from setuptools import setup

setup_args = dict(
    name='wallace-platform',
    packages=['wallace'],
    version="0.12.0",
    description='Wallace, a platform for experimental cultural evolution',
    url='http://github.com/berkeley-cocosci/Wallace',
    author='Berkeley CoCoSci',
    author_email='wallace@cocosci.berkeley.edu',
    license='MIT',
    keywords=['science', 'cultural evolution', 'experiments', 'psychology'],
    classifiers=[],
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
