import threading
import time

class LldbServiceProxy(object):

    def __init__(self, sender, listener):
        self.sender = sender
        self.listener = listener

        self.completion_result = None
        self.completion_condition = threading.Condition()

    def __getattr__(self, name):
        def method_proxy(**args):
            message = {'command': name}
            message.update(args)
            self.sender(message)

        return method_proxy

    def notify_event(self, event):
        listener_method = getattr(self.listener, 'on_' + event['type'])
        args = dict(event)
        del args['type']
        if event['type'] == 'completion':
            self._on_completion(**args)
        else:
            listener_method(**args)

    def handle_completion(self, current_line, cursor_pos, timeout=0.5):
        self.sender({
            'command': 'handle_completion',
            'current_line': current_line,
            'cursor_pos': cursor_pos,
        })

        matches = []
        now = time.time()
        with self.completion_condition:
            self.completion_condition.wait_for(
                lambda: self.completion_result is not None, timeout)
            matches = list(self.completion_result)
            self.completion_result = None
        print("Completion finished in", time.time() - now, "seconds")

        return matches

    def _on_completion(self, matches):
        with self.completion_condition:
            self.completion_result = list(matches)
            self.completion_condition.notify()
