#!/usr/bin/env python3
from setuptools import setup, find_packages

setup(
    name='notes-cli',
    version='0.1',
    packages=find_packages(),
    install_requires=[
        'click',
        'json5'
    ],
    entry_points={
        'console_scripts': [
            'notes=notes.cli:main'
        ]
    }
)