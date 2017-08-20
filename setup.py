#!/usr/bin/env python
from __future__ import absolute_import, division, print_function

from setuptools import setup, find_packages

setup(
    version='0.1.0',
    name='libcloud-virtualbox',
    maintainer='Adi Roiban',
    maintainer_email='adiroiban@gmail.com',
    url='https://github.com/chevah/libcloud-virtualbox',
    classifiers=[
        "Intended Audience :: Developers",
        "License :: OSI Approved :: Apache-2 License",
        "Programming Language :: Python :: 2",
        "Programming Language :: Python :: 2.7",
        ],
    install_requires=[
        'apache-libcloud',
        'chevah-ZSI==2.1',
        ],
    extras_require={
        'test': [
            'coverage',
            'nose',
            'nose-randomly==1.2.5'
            ],
        },
    package_dir={'': 'src'},
    packages=find_packages('src'),
    license="Apache 2",
    zip_safe=False,
    include_package_data=True,
    description='LibCloud 3rd party driver for VirtualBox.',
    long_description=open('README.rst').read(),
    )
