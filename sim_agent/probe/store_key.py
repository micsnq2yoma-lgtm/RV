"""Run interactively INSIDE board Ubuntu; credential is never echoed or logged."""
import getpass
import os
from pathlib import Path
import sys
import warnings


def main():
    if os.name != 'posix' or os.geteuid() != 0 or not sys.stdin.isatty():
        raise SystemExit('Run as root in an interactive Ubuntu terminal, without session recording.')
    folder = Path('/root/.config/rv-agent')
    os.umask(0o077)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    if folder.is_symlink():
        raise SystemExit('Refusing symlink directory')
    folder.chmod(0o700)
    path = folder/'deepseek.key'
    if path.exists() or path.is_symlink():
        raise SystemExit('Key already exists; not overwriting it.')
    # Never fall back to echoed input if the terminal cannot disable echo.
    with warnings.catch_warnings():
        warnings.simplefilter('error', getpass.GetPassWarning)
        value = getpass.getpass('DeepSeek API Key (hidden): ').strip()
    if not value or any(c.isspace() for c in value):
        raise SystemExit('Empty/invalid key; nothing written.')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(value+'\n')
        stream.flush()
        os.fsync(stream.fileno())
    print('Key saved with mode 600. Value omitted.')


if __name__ == '__main__':
    main()
