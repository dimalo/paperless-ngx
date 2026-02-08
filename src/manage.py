#!/usr/bin/env python3
import os
import signal
import sys


def reap_zombies(signum, frame):
    """
    Reaps any child processes that have exited to prevent them from
    becoming zombie processes.
    """
    try:
        while True:
            # -1: any child process
            # os.WNOHANG: do not block if no child process has exited
            pid, _ = os.waitpid(-1, os.WNOHANG)
            if pid <= 0:
                break
    except ChildProcessError:
        # No child processes exist
        pass


if __name__ == "__main__":
    # Register the signal handler for SIGCHLD to reap zombies
    signal.signal(signal.SIGCHLD, reap_zombies)

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "paperless.settings")

    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)
