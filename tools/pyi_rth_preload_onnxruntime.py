"""Preload onnxruntime before PyQt6 runtime hook.

PyInstaller's built-in `pyi_rth_pyqt6` hook imports `PyQt6.QtCore`, which may
cause onnxruntime initialization failure on some Windows environments if ORT is
imported later. Load ORT first to lock a compatible DLL initialization order.
"""

import sys


def _preload_onnxruntime() -> None:
    if sys.platform != 'win32':
        return
    import onnxruntime  # noqa: F401


_preload_onnxruntime()
del _preload_onnxruntime
