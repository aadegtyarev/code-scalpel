from setuptools import setup, find_packages

def read_requirements():
    with open('requirements.txt') as f:
        return [line.strip() for line in f.readlines() if not line.startswith('#')]

setup(
    name='notes-cli',
    version='0.1.0',
    description='CLI для заметок',
    author='Your Name',
    license='MIT',
    packages=find_packages(),
    install_requires=read_requirements(),
    entry_points={
        'console_scripts': [
            'notes-cli=notes_cli.cli:main'
        ]
    }
)