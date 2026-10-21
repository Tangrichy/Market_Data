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
# SDK lives at <repo>/udpapi, i.e. one level above this directory.
UDPAPI_ROOT = os.getenv("GTJA_UDPAPI_ROOT") or os.path.join(os.path.dirname(ROOT), "udpapi")

INCLUDE_DIR = os.path.join(UDPAPI_ROOT, "include")


def _pick_lib_dir():
    """Locate the directory holding libGtjaMdUserApi.so.

    Prefer the gcc9.3.1 build (what the extension is tuned for), but fall back
    to any other shipped gcc variant so a fresh clone builds without edits.
    """
    override = os.getenv("GTJA_UDPAPI_LIB_DIR")
    if override:
        return override

    linux64 = os.path.join(UDPAPI_ROOT, "Linux64")
    for variant in ("gcc9.3.1", "gcc8.3.1", "gcc7.3.1", "gcc4.8.5", "gcc4.4.7"):
        candidate = os.path.join(linux64, variant)
        if os.path.exists(os.path.join(candidate, "libGtjaMdUserApi.so")):
            return candidate
    return os.path.join(linux64, "gcc9.3.1")  # let the compiler report the real error


LIB_DIR = _pick_lib_dir()

for _label, _path in (
    ("头文件目录", INCLUDE_DIR),
    ("动态库目录", LIB_DIR),
):
    if not os.path.isdir(_path):
        raise SystemExit(
            "找不到 %s: %s\n"
            "请确认 udpapi SDK 位于 %s（或设置 GTJA_UDPAPI_ROOT 指向 SDK 根目录）。"
            % (_label, _path, UDPAPI_ROOT)
        )

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
        # pybind11 >= 3.0 requires C++17; the officially built SDK library is
        # ABI-compatible, so building the binding as C++17 is safe.
        cxx_std=17,
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
