# setup.py
from setuptools import setup, find_packages

setup(
    name='notetool',
    version='0.1',
    packages=find_packages(),
    install_requires=[
        'click',
        'pytest'
    ],
    entry_points={
        'console_scripts': [
            'notetool=notetool.cli:cli'
        ]
    }
)