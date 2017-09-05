from setuptools import setup, find_packages

try:
    from pypandoc import convert
    def read_markdown(file: str) -> str:
        return convert(file, "rst")
except ImportError:
    def read_markdown(file: str) -> str:
        return open(file, "r").read()

setup(
    name="yaosadis",
    version="2.0.0",
    packages=find_packages(exclude=["tests"]),
    install_requires=open("requirements.txt", "r").readlines(),
    url="https://github.com/wtsi-hgi/yaosadis",
    license="GPL3",
    description="Yet Another OpenStack Ansible Dynamic Inventory Script",
    long_description=read_markdown("README.md"),
    entry_points={
        "console_scripts": [
            "yaosadis=yaosadis.yaosadis:main"
        ]
    }
)
