import argparse
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

    def on_process_state_changed(self, state):
        event = {'type': 'process_state', 'state': state}
        if state == 'stopped':
            event['line_entry'] = self.service.frame_get_line_entry()
        elif state == 'exited':
            self._stop()
        self.event_queue.put(event)

    def on_command_output(self, output):
        event = {'type': 'command_output', 'output': output}
        self.event_queue.put(event)

    def on_error(self, message):
        event = {'type': 'error', 'message': message}
        self.event_queue.put(event)

    def _process_event_queue(self):
        while self.running:
            event = self.event_queue.get()
            self.send_json(event)
            self.event_queue.task_done()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('address')
    args = parser.parse_args()

    with LldbClient(args.address) as client:
        client.listen_forever()


if __name__ == "__main__":
    main()
