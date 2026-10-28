"""Sockets IPv4 flux uniquement ; socketpair local ; nécessite obligatoirement un namespace réseau isolé."""
import ctypes, os, sys
lib = ctypes.CDLL('libseccomp.so.2', use_errno=True)
lib.seccomp_init.argtypes = [ctypes.c_uint32]
lib.seccomp_init.restype = ctypes.c_void_p
lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
lib.seccomp_rule_add_array.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int,
                                       ctypes.c_uint, ctypes.c_void_p]
lib.seccomp_load.argtypes = [ctypes.c_void_p]
class ArgCmp(ctypes.Structure):
    _fields_ = [('arg', ctypes.c_uint), ('op', ctypes.c_uint),
                ('datum_a', ctypes.c_uint64), ('datum_b', ctypes.c_uint64)]
ctx = lib.seccomp_init(0x7fff0000)
def deny(name, comparisons):
    arr = (ArgCmp * len(comparisons))(*comparisons)
    if lib.seccomp_rule_add_array(ctx, 0x00050001, lib.seccomp_syscall_resolve_name(name), len(arr), arr):
        raise SystemExit('seccomp impossible')
deny(b'socket', [ArgCmp(0, 1, 2, 0)])
deny(b'socketpair', [ArgCmp(0, 1, 1, 0)])
for kind in (2, 3, 4, 5, 6, 10):
    deny(b'socket', [ArgCmp(0, 4, 2, 0), ArgCmp(1, 7, 15, kind)])
if lib.seccomp_load(ctx):
    raise SystemExit('seccomp impossible')
os.execv(sys.argv[1], sys.argv[1:])
