#!/usr/bin/env python
from setuptools import setup, find_packages

setup(
    name='notes_cli',
    version='0.1',
    packages=find_packages(),
    install_requires=[
        'click',
        'pytest',
        'ruff'
    ],
    entry_points={
        'console_scripts': [
            'notes=notes_cli.cli:main'
        ]
    }
)