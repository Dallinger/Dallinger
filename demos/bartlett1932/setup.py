"""Install demo with an entry point in dallinger.experiments."""

from setuptools import setup

try:
    with open('README.rst', 'r') as file:
        long_description = file.read()

except (OSError, IOError) as e:
    with open('README.md', 'r') as file:
        long_description = file.read()

setup_args = dict(
    name='dallinger.bartlett1932',
    version="0.2.0",
    description='Bartlett (1932) demo for Dallinger',
    setup_requires=['setuptools-markdown'],
    long_description_markdown_filename='README.md',
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
        'dallinger.experiments': [
            'Bartlett1932 = demos.bartlett1932.experiment:Bartlett1932',
        ],
    },
)

setup(**setup_args)
