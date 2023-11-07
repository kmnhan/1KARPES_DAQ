from . import Motor


class FakeMotor1(Motor):
    minimum = 0.0
    delta = 1.0
    fix_delta = True

    def move(self, target):
        return target


class FakeMotor2(Motor):
    minimum = 0.0
    delta = 1.0
    fix_delta = True

    def move(self, target):
        return target
