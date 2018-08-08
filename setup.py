"""Install Dallinger as a command line utility."""

from setup_utils import update_pins
from setuptools import setup

setup_args = dict(
    name='dallinger',
    packages=['dallinger'],
    version="4.0.0",
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
        'Programming Language :: Python :: 3.6',
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
            "networkx",
            "odo",
            "openpyxl",  # 2.5 is incompatible with tablib
            "pandas",
            "tablib",
        ],
        'jupyter': [
            "jupyter",
            "ipywidgets",
        ],
    }
)

update_pins(setup_args)

setup(**setup_args)
