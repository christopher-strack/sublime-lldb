from __future__ import absolute_import, print_function

import argparse
import lldb
import socket
import sys
import threading
import xmlrpclib

from SimpleXMLRPCServer import SimpleXMLRPCServer


def state_to_str(state):
    if state == lldb.eStateAttaching:
        return 'attaching'
    elif state == lldb.eStateConnected:
        return 'connected'
    elif state == lldb.eStateCrashed:
        return 'crashed'
    elif state == lldb.eStateDetached:
        return 'detached'
    elif state == lldb.eStateExited:
        return 'exited'
    elif state == lldb.eStateInvalid:
        return 'invalid'
    elif state == lldb.eStateLaunching:
        return 'launching'
    elif state == lldb.eStateRunning:
        return 'running'
    elif state == lldb.eStateStepping:
        return 'stepping'
    elif state == lldb.eStateStopped:
        return 'stopped'
    elif state == lldb.eStateSuspended:
        return 'suspended'
    elif state == lldb.eStateUnloaded:
        return 'unloaded'


class LldbService(object):

    def __init__(self):
        self.debugger = lldb.SBDebugger.Create()
        self.debugger.SetAsync(True)
        self.target = None
        self.process = None
        self.listener_service = None

    def create_target(self, executable_path):
        self.target = self.debugger.CreateTargetWithFileAndArch(
            executable_path, lldb.LLDB_ARCH_DEFAULT)
        return bool(self.target)

    def target_launch(self):
        error = lldb.SBError()
        process_state_listener = lldb.SBListener('process_state_listener')
        self.process = self.target.Launch(
            process_state_listener, None, None, None, None, None, None, 0, False, error)

        thread = threading.Thread(
            target=self._query_process_state,
            args=(self.process, process_state_listener))
        thread.start()

        return bool(self.process)

    def target_set_breakpoint(self, file, line):
        breakpoint = self.target.BreakpointCreateByLocation(file, line)
        return str(breakpoint)

    def process_get_state(self):
        return state_to_str(self.process.GetState())

    def process_get_selected_thread(self):
        return self.process.GetSelectedThread().GetThreadID()

    def process_destroy(self):
        result = self.process.Destroy()
        return bool(result)

    def frame_get_line_entry(self, thread_id, frame_index):
        thread = self.process.GetThreadByID(thread_id)
        frame = thread.GetFrameAtIndex(frame_index)
        line_entry = frame.GetLineEntry()
        file_spec = line_entry.GetFileSpec()
        return {
            'directory': file_spec.GetDirectory(),
            'filename': file_spec.GetFilename(),
            'line': line_entry.GetLine(),
            'column': line_entry.GetColumn(),
        }

    def handle_command(self, command):
        result = lldb.SBCommandReturnObject()
        interpreter = self.debugger.GetCommandInterpreter()
        interpreter.HandleCommand(command, result)
        return result.GetOutput() if result else None

    def state(self):
        return 'started'

    def register_listener(self, port):
        try:
            host_name = 'http://localhost:%s/' % port
            self.listener_service = xmlrpclib.ServerProxy(host_name)
            print('Listener registered at port %s' % port)
            sys.stdout.flush()
            return True
        except Exception as e:
            print(e)

        return False

    def _query_process_state(self, process, listener):
        event = lldb.SBEvent()
        broadcaster = process.GetBroadcaster()
        while True:
            result = listener.WaitForEventForBroadcasterWithType(
                1, broadcaster, lldb.SBProcess.eBroadcastBitStateChanged, event)
            if result:
                if self.listener_service is not None:
                    self.listener_service.notify_process_state(
                        state_to_str(process.GetState()))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        'port',
        type=int,
        help='Port number on that is used by the server',
    )
    args = parser.parse_args()

    try:
        server = SimpleXMLRPCServer(
            ('localhost', args.port),
            allow_none=True,
            logRequests=False,
        )
        print('LLDB RPC server running on localhost:%s' % args.port)
        sys.stdout.flush()
        service = LldbService()
        server.register_instance(service)
        server.serve_forever()
    except socket.error as e:
        sys.exit(e)


if __name__ == "__main__":
    main()
