import socket

from .message import read_json, write_json


class JsonServer(object):

    def __init__(self, server_address):
        self.connection = None

        self.socket = socket.socket(
            socket.AF_UNIX,
            socket.SOCK_STREAM,
        )
        self.socket.bind(server_address)
        self.socket.listen(1)

    def wait_for_connection(self, timeout=None):
        self.socket.settimeout(timeout)
        self.connection, client_address = self.socket.accept()
        self.socket.settimeout(None)

    def close(self):
        self.connection.close()

    def send_json(self, data):
        write_json(self.connection, data)

    def serve_forever(self, callback):
        try:
            while True:
                callback(read_json(self.connection))
        finally:
            self.close()
