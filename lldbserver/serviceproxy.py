
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
        listener_method = getattr(self.listener, 'on_' + event['type'])
        args = event
        del args['type']
        listener_method(**args)
