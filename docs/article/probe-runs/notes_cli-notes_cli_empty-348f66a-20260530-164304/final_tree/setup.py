from setuptools import setup, find_packages

def readme():
    with open('README.md') as f:
        return f.read()

setup(
    name='notes',
    version='0.1',
    description='Notes CLI',
    long_description=readme(),
    long_description_content_type='text/markdown',
    url='https://github.com/yourusername/notes-cli',
    author='Your Name',
    author_email='your.email@example.com',
    packages=find_packages(),
    install_requires=[
        'pytest'
    ],
    entry_points={
        'console_scripts': [
            'notes=notes.cli:main'
        ]
    }
)