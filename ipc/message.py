import struct
import json


_header_size = 4


class ConnectionAbortedError(Exception):
    pass


def read_json(sock):
    header = sock.recv(_header_size)
    if len(header) == 0:
        raise ConnectionAbortedError()
    size = struct.unpack('!i', header)[0]
    data = sock.recv(size - _header_size)
    if len(data) == 0:
        raise ConnectionAbortedError()
    return json.loads(data.decode('utf-8'))


def write_json(sock, data):
    try:
        data = json.dumps(data)
        sock.sendall(struct.pack('!i', len(data) + _header_size))
        sock.sendall(data.encode())
    except OSError:
        raise ConnectionAbortedError()
