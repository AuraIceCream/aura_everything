"""Cheap Windows commit checks before entering native CPU model loaders."""
import sys
import threading


# One process-wide handoff between local generation and learned verification.
# Reentrant because a structured answer also calls the locked Ollama adapter.
MODEL_PHASE_LOCK = threading.RLock()


class MemoryPressureError(RuntimeError):
    pass


def available_memory_mb():
    if sys.platform != 'win32':
        return None
    import ctypes
    from ctypes import wintypes

    class Status(ctypes.Structure):
        _fields_ = [('length', wintypes.DWORD), ('load', wintypes.DWORD),
                    ('total_phys', ctypes.c_ulonglong), ('avail_phys', ctypes.c_ulonglong),
                    ('total_page', ctypes.c_ulonglong), ('avail_page', ctypes.c_ulonglong),
                    ('total_virtual', ctypes.c_ulonglong), ('avail_virtual', ctypes.c_ulonglong),
                    ('avail_extended', ctypes.c_ulonglong)]

    status = Status()
    status.length = ctypes.sizeof(status)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    read = kernel.GlobalMemoryStatusEx
    read.argtypes = [ctypes.POINTER(Status)]
    read.restype = wintypes.BOOL
    if not read(ctypes.byref(status)):
        return None
    return {'physical': status.avail_phys / (1024 ** 2), 'commit': status.avail_page / (1024 ** 2)}


def guard_cpu_model_load(label, required_mb=1536):
    snapshot = available_memory_mb()
    if snapshot is not None and snapshot['commit'] < required_mb:
        raise MemoryPressureError(
            f'Insufficient Windows committed-memory headroom to load {label}: '
            f"{snapshot['commit']:.0f} MiB available, approximately {required_mb} MiB needed for loading. "
            'Close memory-heavy applications and retry. The model and scoring settings have not been changed.')
