SLIT_PORT: int = 5557
CRYO_PORT: int = 5558
MG15_PORT: int = 5559

SLIT_TABLE: tuple[tuple[int, float, bool], ...] = (
    (100, 0.05, False),
    (200, 0.1, False),
    (300, 0.2, False),
    (400, 0.3, False),
    (500, 0.2, True),
    (600, 0.3, True),
    (700, 0.5, True),
    (800, 0.8, True),
    (900, 1.5, True),
)
