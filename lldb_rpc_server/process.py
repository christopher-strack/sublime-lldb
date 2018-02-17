import os
import platform
import subprocess
import socket
import threading
import time
import xmlrpc.client
import xmlrpc.server

from contextlib import closing

from ..sublime_logging import get_logger


logger = get_logger(__name__)


def find_free_port():
    with closing(socket.socket()) as s:
        s.bind(('localhost', 0))
        return s.getsockname()[1]


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


class LldbServerProcess(object):

    def __init__(self, python_binary, lldb_python_lib_directory=None):
        self.lldb_server_port = find_free_port()
        self.listener_server_port = find_free_port()
        self.process = self._run_rpc_server_process(
            python_binary,
            lldb_python_lib_directory,
        )
        self.lldb_service = None
        self.listener_server = None
        self.listener = None

    def connect(self):
        if self.lldb_service is None:
            self._close_listener_server()
            self.lldb_service = self._connect_to_rpc_server()
            self.listener_server = self._run_listener_server()
            self.lldb_service.register_listener(self.listener_server_port)

        return self.lldb_service

    def set_listener(self, listener):
        self.listener = listener

    @property
    def is_running(self):
        return self.process is not None and self.process.returncode is None

    def kill(self):
        if self.process is not None:
            self.process.kill()
            self.process = None

        if self.lldb_service is not None:
            self.lldb_service = None

        self._close_listener_server()

    def _close_listener_server(self):
        if self.listener_server is not None:
            self.listener_server.server_close()
            self.listener_server = None

    def _run_rpc_server_process(self, python_binary, lldb_python_lib_directory):
        current_dir = os.path.dirname(os.path.abspath(__file__))
        server_path = os.path.join(current_dir, 'server.py')

        if lldb_python_lib_directory is not None and \
           not os.path.isdir(lldb_python_lib_directory):
            raise FileNotFoundError(
                'Couldn\'t find LLDB Python plugin. %r is not a valid '
                'directory' % lldb_python_lib_directory
            )

        logger.info('Start RPC server process')

        python_path = find_lldb_python_lib_directory() \
            if lldb_python_lib_directory is None \
            else lldb_python_lib_directory

        env = {} if python_path is None else {'PYTHONPATH': python_path}

        process = subprocess.Popen(
            (python_binary, server_path, str(self.lldb_server_port)),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
        )

        thread = threading.Thread(
            target=self._monitor_rpc_server,
            args=(process,),
        )
        thread.start()

        return process

    def _monitor_rpc_server(self, process):
        encoding = 'utf-8'
        chunk_size = 2 ** 13
        handle = process.stdout
        running = True

        while running:
            try:
                data = os.read(handle.fileno(), chunk_size)
                if data == b'':
                    raise IOError('EOF')
                logger.info(data.decode(encoding).strip())
            except UnicodeDecodeError as e:
                msg = 'Error decoding output using %s - %s'
                logger.error(msg  % (encoding, str(e)))
                running = False
            except IOError:
                process.wait()
                logger.info('RPC server returned with %s' % process.returncode)
                running = False
            except:
                logger.error('RPC server quit unexpectedly')
                running = False

    def _connect_to_rpc_server(self):
        host_name = 'http://localhost:%s/' % self.lldb_server_port
        logger.info('Connecting to RPC server %s' % host_name)
        lldb_service = xmlrpc.client.ServerProxy(host_name)
        retry_count = 0
        retry_time = 0.2
        max_retries = 5
        retry = True

        while retry:
            try:
                lldb_service.state()
                return lldb_service
            except ConnectionRefusedError:
                retry_count += 1

                if retry_count == max_retries:
                    retry = False
                    raise ConnectionRefusedError(
                        'Failed to connect to RPC server',
                    )
                else:
                    time.sleep(retry_time)

    def notify_process_state(self, state):
        if self.listener is not None:
            self.listener.on_process_state_changed(state)

    def _run_listener_server(self):
        logger.info(
            'Start listener server on port %s' % self.listener_server_port)
        listener_server = xmlrpc.server.SimpleXMLRPCServer(
            ('localhost', self.listener_server_port),
            allow_none=True,
            logRequests=False,
        )
        listener_server.register_function(self.notify_process_state)

        thread = threading.Thread(
            target=self._run_listener_service,
            args=(listener_server,),
        )
        thread.start()

        return listener_server

    def _run_listener_service(self, listener_server):
        try:
            listener_server.serve_forever()
        except OSError:
            pass

        logger.info('Listener server closed')

