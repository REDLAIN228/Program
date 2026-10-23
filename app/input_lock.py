"""Cross-process exclusive lease for the desktop mouse; no drivers or injection."""
import os
from pathlib import Path
import tempfile


class InputLease:
    def __init__(self, path=None):
        if path is None:
            if os.name == "nt":
                folder = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir()))/"AnimeDrawer"
                folder.mkdir(parents=True, exist_ok=True)
                path = folder/"desktop-input.lock"
            else:
                path = Path(tempfile.gettempdir())/f"redlain-desktop-input-{os.getuid()}.lock"
        self.path, self.file = Path(path), None

    def acquire(self):
        if self.file is not None: return
        file = self.path.open("a+b")
        if file.tell() == 0:
            file.write(b"0")
            file.flush()
        file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            file.close()
            raise RuntimeError("Другой экземпляр REDLAIN уже управляет мышью. Остановите его перед новым запуском.") from exc
        self.file = file

    def release(self):
        if self.file is None: return
        file, self.file = self.file, None
        try:
            file.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(file.fileno(), fcntl.LOCK_UN)
        finally:
            file.close()
