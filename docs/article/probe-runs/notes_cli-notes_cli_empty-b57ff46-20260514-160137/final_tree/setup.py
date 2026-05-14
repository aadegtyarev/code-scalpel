from setuptools import setup, find_packages

setup(
    name='notes-cli',
    version='0.1.0',
    packages=find_packages(),
    install_requires=[
        'pytest',
        'ruff'
    ],
)