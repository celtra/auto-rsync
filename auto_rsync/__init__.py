import os
import sys
import time
import signal
import logging
import threading
import subprocess
import shlex

import click
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from watchdog.observers.api import DEFAULT_OBSERVER_TIMEOUT


logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')


class COLORS(object):
    PURPLE = '\033[95m'
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    END = '\033[0m'


def _get_what(event):
    return 'directory' if event.is_directory else 'file'


class RSyncEventHandler(FileSystemEventHandler):
    """RSync when the events captured."""

    def __init__(self, local_path, remote_path, rsync_event, rsync_options=''):
        self.local_path = local_path
        self.remote_path = remote_path
        self.rsync_event = rsync_event
        self.rsync_options = rsync_options
        self.rsync()

    @staticmethod
    def log(log, color):
        logging.info('{}{}{}'.format(color, log, COLORS.END))

    def on_moved(self, event):
        super(RSyncEventHandler, self).on_moved(event)

        what = _get_what(event)
        self.log(
            'Moved {}: from {} to {}'.format(
                what,
                event.src_path,
                event.dest_path
            ),
            COLORS.BLUE
        )

        self.rsync()

    def on_created(self, event):
        super(RSyncEventHandler, self).on_created(event)

        what = _get_what(event)
        self.log(
            'Created {}: {}'.format(what, event.src_path),
            COLORS.GREEN
        )

        self.rsync()

    def on_deleted(self, event):
        super(RSyncEventHandler, self).on_deleted(event)

        what = _get_what(event)
        self.log(
            'Deleted {}: {}'.format(what, event.src_path),
            COLORS.RED
        )

        self.rsync()

    def on_modified(self, event):
        super(RSyncEventHandler, self).on_modified(event)

        what = _get_what(event)
        self.log(
            'Modified {}: {}'.format(what, event.src_path),
            COLORS.YELLOW
        )

        self.rsync()

    def rsync(self):
        self.rsync_event.set()


class RSyncThread(threading.Thread):
    def __init__(self, local_path, remote_path, rsync_event, rsync_options, shutdown_event):
        self.local_path = local_path
        self.remote_path = remote_path
        self.rsync_event = rsync_event
        self.rsync_options = rsync_options
        self.shutdown_event = shutdown_event

        threading.Thread.__init__(self)

    @staticmethod
    def log(log, color):
        logging.info('{}{}{}'.format(color, log, COLORS.END))

    def run(self):
        while not self.shutdown_event.is_set():
            while not self.shutdown_event.is_set() and not self.rsync_event.is_set():
                time.sleep(0.1)

            self.rsync_event.clear()
            self.log('RSyncing', COLORS.PURPLE)

            local_path = self.local_path
            remote_path = self.remote_path

            cmd = 'rsync -avP {} {} {}'.format(self.rsync_options, local_path, remote_path)
            self.log(cmd, COLORS.BOLD)

            with open(os.devnull, 'w') as DEVNULL:
                subprocess.call(
                    shlex.split(cmd),
                    stdout=sys.stdout,
                    stderr=subprocess.STDOUT,
                    shell=False,
                )


@click.command()
@click.argument('local-path')
@click.argument('remote-path')
@click.option(
    '--observer-timeout',
    default=DEFAULT_OBSERVER_TIMEOUT,
    help='The observer timeout, default {}'.format(
        DEFAULT_OBSERVER_TIMEOUT
    )
)
@click.option('--rsync-options', default='', help='rsync command options')
@click.option('--rsync-file-opts', default=None, help='file with rsync options')
def main(
    local_path, remote_path,
    observer_timeout, rsync_options, rsync_file_opts
):
    if subprocess.call(['which', 'rsync']) != 0:
        print(
            COLORS.RED +
            'Can\'t find the `rsync` program, you need to install it.' +
            COLORS.END
        )
        sys.exit(1)

    if rsync_file_opts:
        with open(rsync_file_opts) as opts_file:
            opts = map(str.strip, opts_file)
            rsync_options += u' '.join(opts)

    rsync_event = threading.Event()
    shutdown_event = threading.Event()

    class ShutdownException:
        pass

    def shutdown(signum, frame):
        print('Caught signal %d' % signum)
        raise ShutdownException()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    rsync = RSyncThread(local_path, remote_path, rsync_event,
                        rsync_options, shutdown_event)
    rsync.start()

    event_handler = RSyncEventHandler(
        local_path, remote_path, rsync_event, rsync_options)
    observer = Observer(timeout=observer_timeout)
    observer.schedule(event_handler, local_path, recursive=True)
    observer.start()
    try:
        while True:
            time.sleep(1)
    except ShutdownException:
        shutdown_event.set()
        observer.stop()
    observer.join()


if __name__ == '__main__':
    main()
