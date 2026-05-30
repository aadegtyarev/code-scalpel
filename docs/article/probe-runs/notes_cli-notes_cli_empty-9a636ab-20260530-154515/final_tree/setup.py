from setuptools import setup, find_packages

def read_requirements(filename):
    with open(filename) as f:
        return [line.strip() for line in f.readlines() if not line.startswith('#')]

setup(
    name='notes',
    version='0.1.0',
    packages=find_packages(),
    install_requires=read_requirements('requirements.txt'),
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'notes=notes.cli:main'
        ]
    }
)