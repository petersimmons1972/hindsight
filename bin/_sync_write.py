#!/home/linuxbrew/.linuxbrew/bin/python3
"""Descriptor-relative writes for sync-failure-modes.sh.

All target traversal starts from a verified consumer-root directory descriptor.
The helper deliberately accepts only the fixed catalog relative path.
"""
import argparse
import os
import stat
import sys

RELATIVE = ("docs", "vendor", "hindsight", "failure-modes.md")


def fail(message):
    print(f"ERROR: {message}", file=sys.stderr)
    return 1


def parent_fd(root):
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    fd = root_fd
    try:
        for component in RELATIVE[:-1]:
            try:
                os.mkdir(component, 0o755, dir_fd=fd)
            except FileExistsError:
                pass
            next_fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            if fd != root_fd:
                os.close(fd)
            fd = next_fd
        expected = os.path.join(os.path.realpath(root), *RELATIVE[:-1])
        actual = os.readlink(f"/proc/self/fd/{fd}")
        if actual != expected:
            raise RuntimeError(f"parent changed: expected={expected} actual={actual}")
        return root_fd, fd
    except Exception:
        if fd != root_fd:
            os.close(fd)
        os.close(root_fd)
        raise


def replace_regular(root, source, mode):
    root_fd, fd = parent_fd(root)
    tmp = f".hindsight-sync.{os.getpid()}.{os.urandom(8).hex()}"
    try:
        out = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
        try:
            with open(source, "rb") as incoming:
                while chunk := incoming.read(1024 * 1024):
                    offset = 0
                    while offset < len(chunk):
                        offset += os.write(out, chunk[offset:])
            os.fchmod(out, mode)
            os.fsync(out)
        finally:
            os.close(out)
        os.replace(tmp, RELATIVE[-1], src_dir_fd=fd, dst_dir_fd=fd)
    except Exception:
        try:
            os.unlink(tmp, dir_fd=fd)
        except FileNotFoundError:
            pass
        raise
    finally:
        os.close(fd)
        os.close(root_fd)


def replace_link(root, source):
    root_fd, fd = parent_fd(root)
    tmp = f".hindsight-sync.{os.getpid()}.{os.urandom(8).hex()}"
    try:
        os.symlink(os.readlink(source), tmp, dir_fd=fd)
        os.replace(tmp, RELATIVE[-1], src_dir_fd=fd, dst_dir_fd=fd)
    except Exception:
        try:
            os.unlink(tmp, dir_fd=fd)
        except FileNotFoundError:
            pass
        raise
    finally:
        os.close(fd)
        os.close(root_fd)


def remove_target(root):
    root_fd, fd = parent_fd(root)
    try:
        try:
            os.unlink(RELATIVE[-1], dir_fd=fd)
        except FileNotFoundError:
            pass
    finally:
        os.close(fd)
        os.close(root_fd)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("write", "restore", "remove"))
    parser.add_argument("--root", required=True)
    parser.add_argument("--source")
    parser.add_argument("--mode", type=lambda value: int(value, 8))
    args = parser.parse_args()
    try:
        if args.action == "remove":
            remove_target(args.root)
        elif args.action == "write":
            if not args.source or args.mode is None:
                return fail("write requires --source and --mode")
            replace_regular(args.root, args.source, args.mode)
        else:
            if not args.source or args.mode is None:
                return fail("restore requires --source and --mode")
            if stat.S_ISLNK(os.lstat(args.source).st_mode):
                replace_link(args.root, args.source)
            elif stat.S_ISREG(os.stat(args.source).st_mode):
                replace_regular(args.root, args.source, args.mode)
            else:
                return fail(f"unsupported undo backup type: {args.source}")
    except (OSError, RuntimeError) as error:
        return fail(str(error))
    return 0


if __name__ == "__main__":
    sys.exit(main())
