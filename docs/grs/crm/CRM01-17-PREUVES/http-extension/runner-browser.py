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
def deny(name, comparisons=()):
    syscall = lib.seccomp_syscall_resolve_name(name.encode())
    if comparisons:
        arr = (ArgCmp * len(comparisons))(*comparisons)
        rc = lib.seccomp_rule_add_array(ctx, 0x00050001, syscall, len(comparisons), arr)
    else:
        rc = lib.seccomp_rule_add(ctx, 0x00050001, syscall, 0)
    if rc:
        raise SystemExit('seccomp rule failed: ' + name)
# Aucun connect sortant ; socketpair seulement local ; seules familles UNIX et IPv4 autorisées.
deny('connect')
deny('socketpair', [ArgCmp(0, 1, 1, 0)])
deny('socket', [ArgCmp(0, 1, 2, 0)])
# Interdit les sockets réseau non orientées flux (type & 0xf != 1).
for kind in (2, 3, 4, 5, 6, 10):
    deny('socket', [ArgCmp(0, 4, 2, 0), ArgCmp(1, 7, 15, kind)])
if lib.seccomp_load(ctx):
    raise SystemExit('seccomp load failed')
os.execv(sys.argv[1], sys.argv[1:])
