from __future__ import annotations

import importlib
import os
import traceback

# TODO: add fixed step?


class Motor:
    minimum: float | None = None
    maximum: float | None = None
    plugins: dict[str, Motor] = {}

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.plugins[cls.__name__] = cls

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
