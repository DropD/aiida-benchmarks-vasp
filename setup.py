from setuptools import setup, find_packages


VERSION = '0.1.0'


if __name__ == '__main__:
    setup(
        name='aiida-benchmark-vasp',
        version=VERSION,
        packages=find_packages(),
        install_requires=['aiida-core >= 0.11.4', 'aiida-vasp >= 0.2.3']
    )
