import ctypes, os, resource, sys
resource.setrlimit(resource.RLIMIT_AS, (1536 * 1024**2, 1536 * 1024**2))
resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
resource.setrlimit(resource.RLIMIT_NPROC, (7000, 7000))
lib = ctypes.CDLL('libseccomp.so.2', use_errno=True)
lib.seccomp_init.argtypes = [ctypes.c_uint32]
lib.seccomp_init.restype = ctypes.c_void_p
lib.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
lib.seccomp_load.argtypes = [ctypes.c_void_p]
lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
class ArgCmp(ctypes.Structure):
    _fields_ = [('arg', ctypes.c_uint), ('op', ctypes.c_uint),
                ('datum_a', ctypes.c_uint64), ('datum_b', ctypes.c_uint64)]
lib.seccomp_rule_add_array.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int,
                                       ctypes.c_uint, ctypes.POINTER(ArgCmp)]
ctx = lib.seccomp_init(0x7fff0000)
# socket() interdit ; socketpair() autorisé uniquement pour AF_UNIX (boucle TestClient).
if lib.seccomp_rule_add(ctx, 0x00050000 | 1, lib.seccomp_syscall_resolve_name(b'socket'), 0):
    raise SystemExit('seccomp socket rule failed')
comparaison = ArgCmp(0, 1, 1, 0)  # SCMP_CMP_NE, AF_UNIX
if lib.seccomp_rule_add_array(ctx, 0x00050000 | 1, lib.seccomp_syscall_resolve_name(b'socketpair'),
                              1, ctypes.byref(comparaison)):
    raise SystemExit('seccomp socketpair rule failed')
if lib.seccomp_load(ctx):
    raise SystemExit('seccomp load failed')
os.execv(sys.argv[1], sys.argv[1:])
