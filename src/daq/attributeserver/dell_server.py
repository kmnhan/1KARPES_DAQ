"""Server side scripts to be run on the monitoring computer.

Checks for local shared memory on the monitoring computer, and sends the data if it is
available. If the shared memory is not available, no data is sent.
"""

import socket
import struct
import threading
import time

from attributeserver.getter import (
    MANIPULATOR_AXES,
    PORT_POSITION,
    PORT_PRESSURE,
    PORT_TEMPERATURE,
    TEMPERATURE_KEYS,
    get_positions_shm,
    get_pressures_shm,
    get_temperatures_shm,
)


class ServerBase:
    HOST: str = "0.0.0.0"
    PORT: int = 12345

    def __init__(self) -> None:
        self.server_socket = None
        self.running: bool = False

    def start(self) -> None:
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.bind((self.HOST, self.PORT))
        self.server_socket.listen(1)
        self.running = True
        print(f"Server listening on {self.HOST}:{self.PORT}")

        while self.running:
            try:
                client_socket, client_address = self.server_socket.accept()
                print(f"Connection from {client_address}")

                self.post(client_socket)
                client_socket.close()
            except OSError:
                break

    def stop(self) -> None:
        self.running = False
        if self.server_socket:
            self.server_socket.close()
            self.server_socket = None
            print("Server stopped")

    def post(self, socket: socket.socket) -> None:
        raise NotImplementedError

    def run(self) -> None:
        server_thread = threading.Thread(target=self.start)
        server_thread.start()
        return server_thread


class PositionServer(ServerBase):
    PORT = PORT_POSITION

    def post(self, socket: socket.socket) -> None:
        try:
            data = struct.pack(f"{len(MANIPULATOR_AXES)}d", *get_positions_shm())
            socket.sendall(data)
        except Exception:
            return


class PressureServer(ServerBase):
    PORT = PORT_PRESSURE

    def post(self, socket: socket.socket) -> None:
        try:
            data = struct.pack("3f", *get_pressures_shm())
            socket.sendall(data)
        except Exception:
            return


class TemperatureServer(ServerBase):
    PORT = PORT_TEMPERATURE

    def post(self, socket: socket.socket) -> None:
        try:
            data = struct.pack(f"{len(TEMPERATURE_KEYS)}d", *get_temperatures_shm())
            socket.sendall(data)
        except Exception:
            return
