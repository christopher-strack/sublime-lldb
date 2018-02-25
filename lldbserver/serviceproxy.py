

class LldbServiceListener(object):

    def on_process_state_changed(self, state):
        pass

    def on_location_changed(self, location):
        pass

    def on_command_output(self, output):
        pass

    def on_error(self, error):
        pass


class LldbServiceProxy(object):

    def __init__(self, sender, listener):
        self.sender = sender
        self.listener = listener

    def create_target(self, executable_path):
        self.sender({
            'command': 'create_target',
            'executable_path': executable_path,
        })

    def target_launch(self):
        self.sender({'command': 'target_launch'})

    def target_set_breakpoint(self, file, line):
        self.sender({
            'command': 'target_set_breakpoint',
            'file': file,
            'line': line,
        })

    def frame_get_line_entry(self):
        self.sender({'command': 'frame_get_line_entry'})

    def handle_command(self, input):
        self.sender({
            'command': 'handle_command',
            'input': input},
        )

    def notify_event(self, event):
        if event.get('type') == 'process_state':
            process_state = event['state']
            self.listener.on_process_state_changed(process_state)
            if process_state == 'stopped':
                self.listener.on_location_changed(event['line_entry'])
        elif event.get('type') == 'command_output':
            self.listener.on_command_output(event['output'])
        elif event.get('type') == 'error':
            self.listener.on_error(event['message'])
