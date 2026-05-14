from setuptools import setup, find_packages

def read_requirements(filename):
    with open(filename) as f:
        return [line.strip() for line in f.readlines() if not line.startswith('#')]

setup(
    name='notes_cli',
    version='0.1',
    packages=find_packages(),
    install_requires=read_requirements('requirements.txt'),
    entry_points={
        'console_scripts': [
            'notes-cli=notes_cli.cli:main'
        ]
    }
)