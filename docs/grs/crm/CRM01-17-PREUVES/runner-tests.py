import ctypes, os, sys
lib = ctypes.CDLL('libseccomp.so.2', use_errno=True)
lib.seccomp_init.argtypes=[ctypes.c_uint32]
lib.seccomp_init.restype=ctypes.c_void_p
lib.seccomp_syscall_resolve_name.argtypes=[ctypes.c_char_p]
lib.seccomp_rule_add.argtypes=[ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
lib.seccomp_load.argtypes=[ctypes.c_void_p]
ctx=lib.seccomp_init(0x7fff0000)
for name in (b'socket', b'connect'):
 if lib.seccomp_rule_add(ctx, 0x00050001, lib.seccomp_syscall_resolve_name(name), 0):
  raise SystemExit('seccomp impossible')
if lib.seccomp_load(ctx): raise SystemExit('seccomp impossible')
os.execv(sys.argv[1],sys.argv[1:])
