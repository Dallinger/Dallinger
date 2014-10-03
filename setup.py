from setuptools import setup

setup(
    name='wallace',
    version='0.1',
    description='A platform for experimental evolution',
    url='http://github.com/suchow/Wallace',
    author='Berkeley CoCoSci',
    author_email='wallace@cocosci.berkeley.edu',
    license='MIT',
    packages=['wallace'],
    zip_safe=False,
    entry_points={
        'console_scripts': [
            'wallace = wallace.command_line:wallace',
        ],
    })
