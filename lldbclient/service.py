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
            error = lldb.SBError()
            process_state_listener = lldb.SBListener('process_state_listener')
            self.process = self.target.Launch(
                process_state_listener,
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
                self.event_thread = threading.Thread(
                    target=self._query_process_state,
                    args=(self.process, process_state_listener),
                )
                self.event_thread.daemon = True
                self.event_thread.start()
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
        frame = thread.GetFrameAtIndex(0)
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

    def _query_process_state(self, process, listener):
        event = lldb.SBEvent()
        broadcaster = process.GetBroadcaster()
        while self.running:
            result = listener.WaitForEventForBroadcasterWithType(
                lldb.UINT32_MAX,
                broadcaster,
                lldb.SBProcess.eBroadcastBitStateChanged,
                event,
            )
            if result:
                self._notify_process_state(
                    process_state_names[process.GetState()])

    def _notify_process_state(self, state):
        self.listener.on_process_state_changed(state)

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
