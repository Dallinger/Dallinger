"""Install Dallinger as a command line utility."""

from setup_utils import update_pins
from setuptools import setup

setup_args = dict(
    name='dallinger',
    packages=['dallinger', 'dallinger_scripts'],
    version="6.3.1",
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
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Framework :: Pytest',
    ],
    include_package_data=True,
    zip_safe=False,
    entry_points={
        'console_scripts': [
            'dallinger = dallinger.command_line:dallinger',
            'dallinger_heroku_web = dallinger_scripts.web:main',
            'dallinger_heroku_worker = dallinger_scripts.worker:main',
            'dallinger_heroku_clock = dallinger_scripts.clock:main',
        ],
        'dallinger.experiments': [],
        'pytest11': ['pytest_dallinger = dallinger.pytest_dallinger'],
    },
    extras_require={
        'data': [
            "networkx<2.0",  # 2.0 is incompatible with odo
            "odo",
            "openpyxl<2.5",  # 2.5 is incompatible with tablib
            "pandas==0.23.4",
            "tablib<0.12",    # 0.12 is incompatible
        ],
        'jupyter': [
            "jupyter",
            "ipywidgets",
        ],
        'dev': [
            "alabaster",
            "bumpversion",
            "coverage",
            "coverage_pth",
            "codecov",
            "flake8",
            "mock",
            "pycodestyle<2.4",  # 2.4 is incompatible with flake8
            "pypandoc",
            "pytest",
            "recommonmark",
            "sphinxcontrib-spelling",
            "Sphinx",
            "tox",
            "sphinx-js",
            "sphinx_rtd_theme",
        ]
    }
)

update_pins(setup_args)

setup(**setup_args)
