import os
import re

REQUIREMENT_RE = re.compile(r'^(([^=]+)[=<>]+[^#]+)(#.*)?$')


def update_pins(setup_args):
    # Use requirements and constraints to set version pins
    packages = set()
    constraint_files = []
    install_dir = os.path.dirname(__file__)
    with open(os.path.join(install_dir, 'requirements.txt')) as requirements:
        for r in requirements:
            if r.lower().strip() == 'dallinger':
                continue
            if r.startswith('-c '):
                constraint_files.append(r.replace('-c ', '').strip())
            if not r.startswith('-') or r.startswith('#'):
                package = r.strip().lower()
                packages.add(package)

    requirements = []
    for fname in constraint_files:
        with open(os.path.join(install_dir, fname)) as constraints:
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
                        package = package.strip().lower()
                        matches = REQUIREMENT_RE.match(package)
                        if matches:
                            package = matches.group(2)
                        if package == match:
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
