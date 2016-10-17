"""Install Dallinger as a command line utility."""

from setuptools import setup

try:
    with open('README.rst', 'r') as file:
        long_description = file.read()

except (OSError, IOError) as e:
    with open('README.md', 'r') as file:
        long_description = file.read()

setup_args = dict(
    name='dallinger',
    packages=['dallinger'],
    version="2.4.0",
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
