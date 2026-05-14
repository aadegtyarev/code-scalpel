from setuptools import setup, find_packages

def main():
    setup(
        name="notes-cli",
        version="0.1",
        packages=find_packages(),
        install_requires=["pytest"],
        entry_points={
            "console_scripts": [
                "notes=notes:main"
            ]
        }
    )

if __name__ == "__main__":
    main()