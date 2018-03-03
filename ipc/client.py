import socket

from .message import read_json, write_json


class JsonClient(object):
    def __init__(self, server_address):
        self.server_address = server_address
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

    def connect(self):
        self.socket.connect(self.server_address)

    def close(self):
        self.socket.close()

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def send_json(self, data):
        write_json(self.socket, data)

    def receive_json(self):
        return read_json(self.socket)
