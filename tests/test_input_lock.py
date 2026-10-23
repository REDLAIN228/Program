import subprocess
import sys

import pytest

from app.input_lock import InputLease


def test_other_process_cannot_steal_desktop_lease_and_crash_releases_it(tmp_path):
    path = tmp_path/"input.lock"
    first = InputLease(path)
    first.acquire()
    script = "from app.input_lock import InputLease; import sys; lock=InputLease(sys.argv[1]); lock.acquire(); print('acquired'); lock.release()"
    blocked = subprocess.run([sys.executable, "-c", script, str(path)], capture_output=True, text=True)
    assert blocked.returncode != 0 and "Другой экземпляр" in blocked.stderr
    first.release()
    accepted = subprocess.run([sys.executable, "-c", script, str(path)], capture_output=True, text=True)
    assert accepted.returncode == 0 and "acquired" in accepted.stdout
    # A process exiting without explicit unlock still releases the OS lease.
    subprocess.check_call([sys.executable, "-c", "from app.input_lock import InputLease; import sys,os; lock=InputLease(sys.argv[1]); lock.acquire(); os._exit(0)", str(path)])
    final = InputLease(path)
    final.acquire()
    final.release()
