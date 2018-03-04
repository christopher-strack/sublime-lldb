import lldb
import os
import threading


class LldbService(object):

    def __init__(self, listener):
        self.running = True
        self.debugger = lldb.SBDebugger.Create()
        self.debugger.SetAsync(True)
        self.debugger.SetUseColor(False)
        self.target = None
        self.process = None
        self.listener = listener
        self.event_thread = None
        self.executable_path =None

    def create_target(self, executable_path):
        self.executable_path = executable_path.encode('utf-8')
        self.target = self.debugger.CreateTargetWithFileAndArch(
            self.executable_path, lldb.LLDB_ARCH_DEFAULT)
        if not self.target:
            self._notify_error(
                'Couldn\'t create target %r' % self.executable_path)

    def target_launch(self):
        if self.target:
            process_listener = lldb.SBListener('process_listener')
            process_listener.StartListeningForEventClass(
                self.debugger,
                lldb.SBProcess.GetBroadcasterClassName(),
                lldb.SBProcess.eBroadcastBitStateChanged |
                lldb.SBProcess.eBroadcastBitSTDOUT |
                lldb.SBProcess.eBroadcastBitSTDERR,
            )
            thread_listener = lldb.SBListener('thread_listener')
            thread_listener.StartListeningForEventClass(
                self.debugger,
                lldb.SBThread.GetBroadcasterClassName(),
                lldb.SBThread.eBroadcastBitSelectedFrameChanged,
            )
            error = lldb.SBError()
            self.process = self.target.Launch(
                process_listener,
                None,
                None,
                None,
                None,
                None,
                None,
                0,
                False,
                error,
            )

            if error.Success() and self.process:
                self.process_event_thread = threading.Thread(
                    target=self._handle_listener,
                    args=(
                        process_listener,
                        {
                            lldb.SBProcess.eBroadcastBitStateChanged:
                                self._notify_process_state,
                            lldb.SBProcess.eBroadcastBitSTDOUT:
                                self._notify_process_std_out,
                            lldb.SBProcess.eBroadcastBitSTDERR:
                                self._notify_process_std_err,
                        }
                    ),
                )
                self.process_event_thread.daemon = True
                self.process_event_thread.start()

                self.thread_event_thread = threading.Thread(
                    target=self._handle_listener,
                    args=(
                        thread_listener,
                        {
                            lldb.SBThread.eBroadcastBitSelectedFrameChanged:
                                self._notify_location,
                        }
                    ),
                )
                self.thread_event_thread.daemon = True
                self.thread_event_thread.start()
            else:
                self._notify_error(
                    'Couldn\'t launch target %r' % self.executable_path)
        else:
            self._notify_error('No target created yet')

    def target_set_breakpoint(self, file, line):
        breakpoint = self.target.BreakpointCreateByLocation(
            file.encode('utf-8'),
            line,
        )
        if not breakpoint:
            self._notify_error('Couldn\'t set breakpoint %s:%i' % (file, line))

    def target_delete_breakpoint(self, file, line):
        file = os.path.basename(file)
        self.handle_command(
            'breakpoint clear -f %s -l %s' % (file, line))

    def process_kill(self):
        self.process.Kill()

    def frame_get_line_entry(self):
        thread = self.process.GetSelectedThread()
        frame = thread.GetSelectedFrame()
        line_entry = frame.GetLineEntry()
        file_spec = line_entry.GetFileSpec()
        if file_spec:
            return {
                'directory': file_spec.GetDirectory(),
                'filename': file_spec.GetFilename(),
                'line': line_entry.GetLine(),
                'column': line_entry.GetColumn(),
            }

    def handle_command(self, input):
        result = lldb.SBCommandReturnObject()
        interpreter = self.debugger.GetCommandInterpreter()
        interpreter.HandleCommand(input.encode('utf-8'), result)
        if result.Succeeded():
            self.listener.notify_event(
                'command_finished', output=result.GetOutput(), success=True)
        else:
            self.listener.notify_event(
                'command_finished', output=result.GetError(), success=False)

    def _handle_listener(self, listener, callbacks):
        while self.running:
            event = lldb.SBEvent()
            result = listener.WaitForEvent(lldb.UINT32_MAX, event)
            if result and event.IsValid():
                callback = callbacks.get(event.GetType())
                if callback is not None:
                    callback(event)

    def _notify_process_state(self, event):
        state = process_state_names[lldb.SBProcess.GetStateFromEvent(event)]
        self.listener.notify_event(
            'process_state',
            state=state,
        )
        self._notify_location(event)

    def _notify_location(self, event):
        line_entry = self.frame_get_line_entry()
        if line_entry:
            self.listener.notify_event('location', line_entry=line_entry)

    def _notify_process_std_out(self, event):
        output = self.process.GetSTDOUT(lldb.UINT32_MAX)
        if output:
            output = output.replace('\r', '')
            self.listener.notify_event('process_std_out', output=output)

    def _notify_process_std_err(self, event):
        output = self.process.GetSTDERR(lldb.UINT32_MAX)
        if output:
            output = output.replace('\r', '')
            self.listener.notify_event('process_std_err', output=output)

    def _notify_error(self, error):
        self.listener.notify_event('error', error=error)


process_state_names = {
    lldb.eStateAttaching: 'attaching',
    lldb.eStateConnected: 'connected',
    lldb.eStateCrashed: 'crashed',
    lldb.eStateDetached: 'detached',
    lldb.eStateExited: 'exited',
    lldb.eStateInvalid: 'invalid',
    lldb.eStateLaunching: 'launching',
    lldb.eStateRunning: 'running',
    lldb.eStateStepping: 'stepping',
    lldb.eStateStopped: 'stopped',
    lldb.eStateSuspended: 'suspended',
    lldb.eStateUnloaded: 'unloaded',
}
