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
    data_size = size - _header_size
    data = b''
    while len(data) < data_size:
        packet = sock.recv(data_size - len(data))
        if len(packet) == 0:
            raise ConnectionAbortedError()
        data += packet
    return json.loads(data.decode('utf-8'))


def write_json(sock, data):
    try:
        data = json.dumps(data)
        sock.sendall(struct.pack('!i', len(data) + _header_size))
        sock.sendall(data.encode())
    except OSError:
        raise ConnectionAbortedError()
