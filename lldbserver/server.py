import os
import platform
import subprocess
import tempfile
import threading

from ipc.message import ConnectionClosedError
from ipc.server import JsonServer

from .serviceproxy import LldbServiceProxy


def find_lldb_python_lib_directory():
    candidate_directories = []
    if platform.system() == 'Darwin':
        output = subprocess.check_output(['xcode-select', '--print-path'])
        xcode_dir = output.decode('utf-8').strip()
        if xcode_dir:
            candidate_directories.append(os.path.join(
                xcode_dir,
                '../SharedFrameworks/LLDB.framework/Resources/Python',
            ))

            candidate_directories.append(os.path.join(
                xcode_dir,
                'Library/PrivateFrameworks/LLDB.framework/Resources/Python',
            ))

            candidate_directories.append(
                '/System/Library/PrivateFrameworks/LLDB.framework/'
                'Resources/Python',
            )

    for d in candidate_directories:
        if os.path.isdir(d):
            return d

    return None


class LldbServer(object):

    connection_timeout = 5  # time in seconds

    def __init__(
        self,
        python_binary,
        lldb_python_lib_directory,
        server_listener,
        service_listener,
    ):
        self.server_address = tempfile.mktemp()
        self.server = JsonServer(self.server_address)
        self.server_listener = server_listener
        self.lldb_service = LldbServiceProxy(
            self.server.send_json, service_listener)
        self.process = self._run_client_process(
            python_binary, lldb_python_lib_directory,
        )
        self.server.wait_for_connection(self.connection_timeout)
        self._run_listener_thread()
        self.running = True

    def _run_client_process(self, python_binary, lldb_python_lib_directory):
        python_path = find_lldb_python_lib_directory() \
            if lldb_python_lib_directory is None \
            else lldb_python_lib_directory
        env = {} if python_path is None else {'PYTHONPATH': python_path}

        current_directory = os.path.dirname(os.path.realpath(__file__))
        process = subprocess.Popen(
            (python_binary, 'run-lldb-client.py', self.server_address),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            cwd=os.path.join(current_directory, '..'),
        )

        monitor_thread = threading.Thread(
            target=self._monitor_process_server,
            args=(process,),
        )
        monitor_thread.start()

        return process

    def _run_listener_thread(self):
        listener_thread = threading.Thread(
            target=self._process_listener_thread,
        )
        listener_thread.daemon = True
        listener_thread.start()

    def _process_listener_thread(self):
        try:
            self.server.serve_forever(self._on_event)
        except ConnectionClosedError:
            self._on_stopped()

    def _on_event(self, event):
        self.lldb_service.notify_event(event)

        if event['type'] == 'process_state' and event['state'] == 'exited':
            self.lldb_service.stop()

    def _monitor_process_server(self, process):
        encoding = 'utf-8'
        chunk_size = 2 ** 13
        handle = process.stdout
        running = True

        while running:
            try:
                data = os.read(handle.fileno(), chunk_size)
                if data == b'':
                    raise IOError('EOF')
                print(data.decode(encoding).strip())
            except UnicodeDecodeError as e:
                msg = 'Error decoding output using %s - %s'
                print(msg  % (encoding, str(e)))
                running = False
            except IOError:
                process.wait()
                print('Client returned with %s' % process.returncode)
                running = False
            except:
                print('Client quit unexpectedly')
                running = False

        self._on_stopped()

    def _on_stopped(self):
        if self.running:
            self.running = False
            self.server_listener.on_server_stopped()
