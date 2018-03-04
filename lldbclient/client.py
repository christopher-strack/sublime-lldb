import threading

from Queue import Queue

from ipc.client import JsonClient

from .service import LldbService


class LldbClient(JsonClient):

    def __init__(self, server_address):
        self.event_queue = Queue()
        self.service = LldbService(self)
        self.event_thread = None
        self.running = True

        self.sender_thread = threading.Thread(
            target=self._process_event_queue,
        )
        self.sender_thread.daemon = True
        self.sender_thread.start()

        super(LldbClient, self).__init__(server_address)

    def listen_forever(self):
        while self.running:
            self._on_message(self.receive_json())

    def notify_event(self, name, **args):
        event = {'type': name}
        event.update(args)
        self.event_queue.put(event)

    def _on_message(self, message):
        command = message.get('command', None)
        if command == 'stop':
            self._stop()
        else:
            func = getattr(self.service, command)
            del message['command']
            func(**message)

    def _stop(self):
        self.service.running = False
        self.running = False

    def _process_event_queue(self):
        while self.running:
            event = self.event_queue.get()
            self.send_json(event)
            self.event_queue.task_done()
