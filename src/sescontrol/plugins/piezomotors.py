import zmq

from . import Motor


class _PiezoMotor(Motor):
    PORT: int = 42623
    AXIS: str | None = None  # motor name

    def __init__(self):
        if self.CHANNEL not in range(6):
            raise ValueError("Channel index must be in range(6)")

    def move(self, target):
        # print(f"FM1 {target}")

        # self.socket.send_string()
        return target
    
    # @property
    # def minimum(self):
    #     context = zmq.Context.instance()
    #     socket: zmq.Socket = context.socket(zmq.REQ)
    #     socket.connect(f"tcp://localhost:{self.PORT}")
    #     socket.send(b"")
    #     return socket.recv_json()

    def pre_motion(self):
        context = zmq.Context.instance()
        if not context:
            context = zmq.Context()
        self.socket = context.socket(zmq.REQ)
        self.socket.connect(f"tcp://localhost:{self.PORT}")

    def post_motion(self):
        self.socket.close()


class X(_PiezoMotor):
    AXIS = "X"


class Y(_PiezoMotor):
    AXIS = "Y"


class Z(_PiezoMotor):
    AXIS = "Z"


class Polar(_PiezoMotor):
    AXIS = "P"


class Tilt(_PiezoMotor):
    AXIS = "T"


class Azi(_PiezoMotor):
    AXIS = "A"
