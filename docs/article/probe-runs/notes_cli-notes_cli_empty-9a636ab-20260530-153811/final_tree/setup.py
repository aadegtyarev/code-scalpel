from setuptools import setup, find_packages

def read_requirements(filename):
    with open(filename) as f:
        return [line.strip() for line in f.readlines() if not line.startswith('#')]

setup(
    name='notes',
    version='0.1.0',
    description='A simple CLI for managing notes',
    author='Your Name',
    author_email='your.email@example.com',
    url='https://github.com/yourusername/notes-cli',
    packages=find_packages(),
    install_requires=read_requirements('requirements.txt'),
    entry_points={
        'console_scripts': [
            'notes=notes.cli:main'
        ]
    },
    classifiers=[
        'Programming Language :: Python :: 3',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
    ],
    python_requires='>=3.7',
)