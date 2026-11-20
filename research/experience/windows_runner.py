"""Run the unchanged kit transcript renderer under native Windows Python.

Git Bash resolves npm .cmd launchers and extensionless CLI scripts. The renderer
still reads the original events and reports the original process exit status.
No global Python, CLI configuration or locked source file is modified.
"""
import os
from pathlib import Path
import runpy
import shlex
import signal
import subprocess
import sys
import uuid


class ProcessJob:
    """Own this one Bash/CLI tree, including MSYS exec's replacement processes."""
    def __init__(self, proc):
        import ctypes as c
        from ctypes import wintypes as w

        class Basic(c.Structure):
            _fields_ = [('process_time', c.c_int64), ('job_time', c.c_int64), ('flags', w.DWORD),
                        ('minimum', c.c_size_t), ('maximum', c.c_size_t), ('process_limit', w.DWORD),
                        ('affinity', c.c_size_t), ('priority', w.DWORD), ('scheduling', w.DWORD)]

        class Extended(c.Structure):
            _fields_ = [('basic', Basic), ('io', c.c_uint64 * 6), ('process_memory', c.c_size_t),
                        ('job_memory', c.c_size_t), ('peak_process_memory', c.c_size_t),
                        ('peak_job_memory', c.c_size_t)]

        self.kernel = c.WinDLL('kernel32', use_last_error=True)
        k = self.kernel
        k.CreateJobObjectW.argtypes = [c.c_void_p, w.LPCWSTR]
        k.CreateJobObjectW.restype = w.HANDLE
        k.SetInformationJobObject.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD]
        k.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        k.TerminateJobObject.argtypes = [w.HANDLE, w.UINT]
        k.QueryInformationJobObject.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD, c.c_void_p]
        k.CloseHandle.argtypes = [w.HANDLE]
        self.handle = k.CreateJobObjectW(None, None)
        limits = Extended()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.handle or not k.SetInformationJobObject(self.handle, 9, c.byref(limits), c.sizeof(limits)) or not k.AssignProcessToJobObject(self.handle, int(proc._handle)):
            error = c.get_last_error()
            if self.handle:
                k.CloseHandle(self.handle)
            proc.kill()
            proc.wait()
            raise OSError(error, 'Cannot isolate the learning process tree')

    def close(self):
        import ctypes as c
        import time
        self.kernel.TerminateJobObject(self.handle, 1)
        # The four time fields occupy 32 bytes; ActiveProcesses is DWORD 10.
        accounting = (c.c_uint32 * 12)()
        deadline = time.monotonic() + 5
        while self.kernel.QueryInformationJobObject(self.handle, 1, c.byref(accounting), c.sizeof(accounting), None):
            if accounting[10] == 0 or time.monotonic() >= deadline:
                break
            time.sleep(.05)
        self.kernel.CloseHandle(self.handle)


def native_path(value, bash):
    if value.startswith('/'):
        # Git Bash can alias the user's Temp directory as /tmp, in addition
        # to drive paths such as /d. Its own converter knows these mounts.
        cygpath = Path(bash).parent.parent/'usr/bin/cygpath.exe'
        return subprocess.check_output([str(cygpath), '-w', value], text=True).strip()
    return value


def first_executable(command):
    # Windows shutil.which skips extensionless Bash launchers and can therefore
    # select a different installed .exe later on PATH. Respect Bash's ordering.
    suffixes = ('', *os.environ.get('PATHEXT', '.EXE;.CMD;.BAT').lower().split(';'))
    for folder in os.get_exec_path():
        for suffix in suffixes:
            candidate = Path(folder)/(command + suffix)
            if candidate.is_file():
                return str(candidate)
    return None


def main():
    bash, script, *args = sys.argv[1:]
    script = native_path(script, bash)
    args = [native_path(arg, bash) for arg in args]
    if script.startswith('-'):
        # The runner also invokes python3 -c and feeds helper programs on stdin.
        os.execv(sys.executable, [sys.executable, script, *args])
    if os.name == 'nt' and Path(script).name == 'render_stream.py':
        # Native Windows has no SIGHUP. This maps its redundant handler setup
        # to SIGTERM; timeout cleanup uses the call's owned process tree.
        if not hasattr(signal, 'SIGHUP'):
            signal.SIGHUP = signal.SIGTERM
        original = subprocess.Popen

        def spawn(command, *positional, **kwargs):
            executable = first_executable(command[0])
            if executable and Path(executable).suffix.lower() == '.exe':
                return original([executable, *command[1:]], *positional, **kwargs)
            # Avoid passing quoted TOML/JSON through Windows' and Bash's two
            # different command-line parsers. A private script preserves argv.
            launcher = Path.cwd()/('.ac-cli-'+uuid.uuid4().hex[:8]+'.sh')
            # open(newline=), not write_text(newline=): that is Python 3.10+.
            with open(launcher, 'w', encoding='utf-8', newline='\n') as stream:
                stream.write('#!/usr/bin/env bash\nexport MSYS2_ARG_CONV_EXCL="*"\nexec '+shlex.join(command)+'\n')
            return original([bash, launcher.as_posix()], *positional, **kwargs)

        subprocess.Popen = spawn
    sys.argv = [script, *args]
    runpy.run_path(script, run_name='__main__')


if __name__ == '__main__':
    main()
