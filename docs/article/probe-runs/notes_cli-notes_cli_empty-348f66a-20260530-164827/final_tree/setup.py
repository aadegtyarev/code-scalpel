from setuptools import setup, find_packages

def install_requirements():
    with open('requirements.txt') as f:
        return [line.strip() for line in f.readlines()]

setup(
    name='notes',
    version='0.1',
    packages=find_packages(),
    install_requires=install_requirements(),
    entry_points={
        'console_scripts': [
            'notes = app.__main__:main'
        ]
    }
)