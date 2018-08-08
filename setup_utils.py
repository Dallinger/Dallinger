import os
import re


def update_pins(setup_args):
    # Use requirements and constraints to set version pins
    packages = set()
    with open('./requirements.txt') as requirements:
        for r in requirements:
            if r.lower().strip() == 'dallinger':
                continue
            if not r.startswith('-') or r.startswith('#'):
                packages.add(r.strip().lower())

    requirements = []
    REQUIREMENT_RE = re.compile(r'^(([^=]+)==[^#]+)(#.*)?$')
    with open('./constraints.txt') as constraints:
        for c in constraints:
            matches = REQUIREMENT_RE.match(c.strip())
            if not matches:
                continue
            match = matches.group(2).lower().strip()
            req = matches.group(1).strip()
            if match in packages:
                requirements.append(req)

            # pin extra requirements
            for extra in setup_args['extras_require']:
                extra_packages = setup_args['extras_require'][extra]
                for i, package in enumerate(extra_packages[:]):
                    if package.lower() == match:
                        extra_packages[i] = req

    if requirements:
        setup_args['install_requires'] = requirements

    # If not on Heroku, install setuptools-markdown.
    try:
        os.environ["DYNO"]
    except KeyError:
        setup_args.update({
            "setup_requires": ['setuptools-markdown==0.2'],
            "long_description_markdown_filename": 'README.md',
        })
