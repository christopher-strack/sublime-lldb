import lldb
import threading


class LldbService(object):

    def __init__(self, listener):
        self.running = True
        self.debugger = lldb.SBDebugger.Create()
        self.debugger.SetAsync(True)
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
                    target=self._handle_process_listener,
                    args=(process_listener,),
                )
                self.process_event_thread.daemon = True
                self.process_event_thread.start()

                self.thread_event_thread = threading.Thread(
                    target=self._handle_thread_listener,
                    args=(thread_listener,),
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

    def frame_get_line_entry(self):
        thread = self.process.GetSelectedThread()
        frame = thread.GetSelectedFrame()
        line_entry = frame.GetLineEntry()
        file_spec = line_entry.GetFileSpec()
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
            self.listener.on_command_output(result.GetOutput())
        else:
            self.listener.on_error(result.GetError())

    def _handle_process_listener(self, listener):
        while self.running:
            event = lldb.SBEvent()
            result = listener.WaitForEvent(lldb.UINT32_MAX, event)
            if result and event.IsValid():
                event_type = event.GetType()
                if event_type & lldb.SBProcess.eBroadcastBitStateChanged:
                    state = lldb.SBProcess.GetStateFromEvent(event)
                    self._notify_process_state(process_state_names[state])
                    self._notify_location(self.frame_get_line_entry())
                elif event_type & lldb.SBProcess.eBroadcastBitSTDOUT:
                    output = self.process.GetSTDOUT(lldb.UINT32_MAX)
                    if output:
                        self._notify_process_std_out(output)
                elif event_type & lldb.SBProcess.eBroadcastBitSTDERR:
                    output = self.process.GetSTDERR(lldb.UINT32_MAX)
                    if output:
                        self._notify_process_std_err(output)

    def _handle_thread_listener(self, listener):
        while self.running:
            event = lldb.SBEvent()
            result = listener.WaitForEvent(lldb.UINT32_MAX, event)
            if result and event.IsValid():
                event_type = event.GetType()
                if event_type & lldb.SBThread.eBroadcastBitSelectedFrameChanged:
                    self._notify_location(self.frame_get_line_entry())

    def _notify_process_state(self, state):
        self.listener.on_process_state_changed(state)

    def _notify_location(self, line_entry):
        self.listener.on_location_changed(line_entry)

    def _notify_process_std_out(self, state):
        self.listener.on_process_std_out(state)

    def _notify_process_std_err(self, state):
        self.listener.on_process_std_err(state)

    def _notify_error(self, error):
        self.listener.on_error(error)


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
