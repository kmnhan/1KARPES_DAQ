from . import Motor


class FakeMotor1(Motor):
    minimum = 0.0

    def __init__(self):
        pass

    def move(self, target):
        print(f"FM1 {target}")
        return target


class FakeMotor2(Motor):
    minimum = 0.0

    def __init__(self):
        pass

    def move(self, target):
        print(f"FM2 {target}")
        return target
