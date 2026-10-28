import ctypes, os, resource, sys
resource.setrlimit(resource.RLIMIT_AS, (1536 * 1024**2, 1536 * 1024**2))
resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
resource.setrlimit(resource.RLIMIT_NPROC, (96, 96))
lib = ctypes.CDLL('libseccomp.so.2', use_errno=True)
lib.seccomp_init.argtypes = [ctypes.c_uint32]
lib.seccomp_init.restype = ctypes.c_void_p
lib.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
lib.seccomp_load.argtypes = [ctypes.c_void_p]
lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
ctx = lib.seccomp_init(0x7fff0000)
for name in (b'socket', b'socketpair'):
    if lib.seccomp_rule_add(ctx, 0x00050000 | 1, lib.seccomp_syscall_resolve_name(name), 0):
        raise SystemExit('seccomp rule failed')
if lib.seccomp_load(ctx):
    raise SystemExit('seccomp load failed')
os.execv(sys.argv[1], sys.argv[1:])
