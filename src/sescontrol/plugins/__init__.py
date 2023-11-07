from __future__ import annotations

import enum
import importlib
import os
import traceback


class Motor:
    """Base class for implementing motor support.

    In order to add a new motor, subclass this class and override the `move` method. The
    return value of `move` must be the final position of the motor after the movement.
    It must block (i.e., it must not return) until the motor has reached the target
    position. Place the .py file containing the inherited class in the plugins folder,
    and it will be automatically detected. The `__name__` of the inherited class will be
    displayed on the motor selection window.

    See examples in `fakemotor.py` and `piezomotors.py`.

    Note that `pre_motion` and `post_motion` is only called once per scan. Everything
    that needs to happen with each step must be included in `move`.

    """

    minimum: float | None = None
    maximum: float | None = None
    delta: float | None = None
    fix_delta: bool = False

    def move(self, target):
        pass

    def pre_motion(self):
        pass

    def post_motion(self):
        pass

    plugins: dict[str, Motor] = {}  #: not to be overloaded

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if not cls.__name__.startswith("_"):
            cls.plugins[cls.__name__] = cls


for fname in os.listdir(os.path.dirname(os.path.abspath(__file__))):
    if (
        not fname.startswith(".")
        and not fname.startswith("__")
        and fname.endswith(".py")
    ):
        try:
            importlib.import_module(__name__ + "." + os.path.splitext(fname)[0])
        except Exception:
            traceback.print_exc()
