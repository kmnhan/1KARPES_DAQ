from __future__ import annotations

import enum
import importlib
import os
import traceback


class Motor:
    plugins: dict[str, Motor] = {}
    minimum: float | None = None
    maximum: float | None = None
    delta: float | None = None
    fix_delta: bool = False

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if not cls.__name__.startswith("_"):
            cls.plugins[cls.__name__] = cls

    def move(self, target):
        pass

    def pre_motion(self):
        pass

    def post_motion(self):
        pass


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
