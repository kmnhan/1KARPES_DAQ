import socket
import struct
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

from pymodbus.client import ModbusTcpClient
from qtpy import QtCore

from mg15 import mg15


def _receive_exact(connection: socket.socket, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = connection.recv(size - len(data))
        if not chunk:
            raise EOFError("Modbus client disconnected before completing the request")
        data.extend(chunk)
    return bytes(data)


class MG15ModbusTests(unittest.TestCase):
    def test_polling_reads_full_register_block_with_original_unit_id(self):
        # A real TCP response exercises the 250-byte payload rejected by 3.7.0.
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            server.settimeout(2)

            def respond():
                requests = []
                connection, _ = server.accept()
                with connection:
                    connection.settimeout(2)
                    for _ in range(3):
                        transaction, protocol, length, unit = struct.unpack(
                            ">HHHB", _receive_exact(connection, 7)
                        )
                        function, address, count = struct.unpack(
                            ">BHH", _receive_exact(connection, length - 1)
                        )
                        requests.append((unit, function, address, count))
                        values = list(range(address, address + count))
                        if address == 1100:
                            values = [1]
                        payload = bytes([function, count * 2]) + struct.pack(
                            ">" + "H" * count, *values
                        )
                        connection.sendall(
                            struct.pack(
                                ">HHHB", transaction, protocol, len(payload) + 1, unit
                            )
                            + payload
                        )
                return requests

            connection = mg15.MG15Connection("127.0.0.1")
            samples = []

            def stop_after_sample(updated, registers, remote):
                samples.append((registers, remote))
                connection.stopped.set()

            connection.sigRead.connect(
                stop_after_sample, QtCore.Qt.ConnectionType.DirectConnection
            )
            client = ModbusTcpClient(
                "127.0.0.1", port=server.getsockname()[1], timeout=1, retries=1
            )
            self.addCleanup(client.close)
            with ThreadPoolExecutor(max_workers=1) as pool:
                response = pool.submit(respond)
                with mock.patch.object(
                    mg15, "ModbusTcpClient", return_value=client
                ) as create_client:
                    connection.run()
                requests = response.result(timeout=3)

        create_client.assert_called_once_with("127.0.0.1", port=502)
        assert requests == [(0, 3, 0, 125), (0, 3, 125, 76), (0, 3, 1100, 1)]
        assert samples == [(list(range(201)), True)]


if __name__ == "__main__":
    unittest.main()
