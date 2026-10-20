#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Build script for Guotai Junan UDP Market Data API Python binding.

Usage:
    source /opt/conda/etc/profile.d/conda.sh && conda activate py39
    python setup.py build_ext --inplace
    # or
    pip install .
"""
from setuptools import setup, Extension
from pybind11.setup_helpers import Pybind11Extension, build_ext
import pybind11
import os

# ---------------------------------------------------------------------------
# Paths to the official C++ API header and library
# ---------------------------------------------------------------------------
ROOT = os.path.dirname(os.path.abspath(__file__))
UDPAPI_ROOT = os.path.dirname(ROOT)  # /root/private_data/trading/udpapi

INCLUDE_DIR = os.path.join(UDPAPI_ROOT, "include")
LIB_DIR = os.path.join(UDPAPI_ROOT, "Linux64", "gcc9.3.1")

# Use rpath so the extension module can locate libGtjaMdUserApi.so at runtime
# without requiring LD_LIBRARY_PATH.
RUNTIME_LIB_DIR = LIB_DIR  # absolute path; alternatively use $ORIGIN after copying the .so

ext_modules = [
    Pybind11Extension(
        "gtja_udp_api",
        sources=[os.path.join(ROOT, "gtja_udp_api.cpp")],
        include_dirs=[INCLUDE_DIR, pybind11.get_include()],
        library_dirs=[LIB_DIR],
        libraries=["GtjaMdUserApi"],  # linker will look for libGtjaMdUserApi.so
        # C++11 is enough for the API; keep compatible with the officially built library.
        cxx_std=11,
        # Make sure the dynamic linker finds the shared library at load time.
        runtime_library_dirs=[RUNTIME_LIB_DIR],
        extra_link_args=["-Wl,-rpath," + RUNTIME_LIB_DIR],
    ),
]

setup(
    name="gtja-udp-api",
    version="3.7.0.6",
    description="Python binding for Guotai Junan UDP Market Data API V3",
    ext_modules=ext_modules,
    cmdclass={"build_ext": build_ext},
    zip_safe=False,
)
