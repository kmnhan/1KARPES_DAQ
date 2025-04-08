import numpy as np


def jones_hwp(theta) -> np.ndarray:
    """Jones matrix for a half-wave plate (HWP) with fast axis at angle theta."""
    theta = np.deg2rad(theta)
    c, s = np.cos(2 * theta), np.sin(2 * theta)
    return np.array([[c, s], [s, -c]])


def jones_qwp(theta) -> np.ndarray:
    """Jones matrix for a quarter-wave plate (QWP) with fast axis at angle theta."""
    theta = np.deg2rad(theta)
    c, s = np.cos(2 * theta), np.sin(2 * theta)
    return (1 / np.sqrt(2)) * np.array([[1 + 1j * c, 1j * s], [1j * s, 1 - 1j * c]])


def get_phase_diff(pol) -> float:
    """Get the phase difference of the polarization vector."""
    Ex, Ey = pol
    # Compute phase difference
    delta = np.angle(Ey) - np.angle(Ex)
    # Normalize delta to [-π, π]
    return (delta + np.pi) % (2 * np.pi) - np.pi


def is_circular(pol, tol=1e-3) -> bool:
    """Check if the polarization is circular."""
    # For circular polarization, the amplitudes should be equal
    # and the phase difference should be ±π/2 (modulo 2π).
    if not np.isclose(np.abs(pol[0]), np.abs(pol[1]), atol=tol):
        return False

    return np.isclose(np.abs(get_phase_diff(pol)), np.pi / 2, atol=tol)


def is_linear(pol, tol=1e-3) -> bool:
    """Check if the polarization is linear."""
    if np.isclose(pol[0], 0, atol=tol) or np.isclose(pol[1], 0, atol=tol):
        return True
    return np.isclose(np.sin(get_phase_diff(pol)), 0, atol=tol)


def get_handedness(pol, tol=1e-3) -> str:
    """Get the handedness of the polarization.

    Returns +1 for left-handed and -1 for right-handed elliptical/circular polarization,
    and 0 for linear polarization.
    """
    if is_linear(pol, tol=tol):
        return 0
    return np.sign(np.sin(get_phase_diff(pol)))


def polarization_info(pol, tol=1e-3) -> str:
    """Human-readable description of the polarization state."""
    if is_linear(pol, tol):
        Ex, Ey = pol
        if np.isclose(np.abs(Ex), 0, atol=tol):
            return "Linear (V)"
        if np.isclose(np.abs(Ey), 0, atol=tol):
            return "Linear (H)"

        angle_deg = np.degrees(np.arctan2(np.abs(Ey), np.abs(Ex)))

        return f"Linear {angle_deg:.1f}°"

    handedness = "R" if get_handedness(pol, tol) < 1 else "L"

    if is_circular(pol, tol):
        return f"Circular ({handedness})"

    return f"Elliptical ({handedness})"


def polarization_integer(pol, tol=1e-3) -> float:
    """Convert polarization state to an integer.

    RC: -1, LH: 0, LC: 1, LV: 2
    """
    info = polarization_info(pol, tol)

    match info:
        case "Circular (R)":
            return -1.0
        case "Linear (H)":
            return 0.0
        case "Circular (L)":
            return 1.0
        case "Linear (V)":
            return 2.0
        case _:
            return np.nan


def calculate_polarization(hwp_angle: float, qwp_angle: float) -> np.ndarray:
    """Calculate the polarization state after passing through a HWP and QWP.

    Assumes initial LV polarization.

    Parameters
    ----------
    hwp_angle : float
        Angle of the half-wave plate (HWP) fast axis in degrees.
        If NaN, the HWP is not present.
    qwp_angle : float
        Angle of the quarter-wave plate (QWP) fast axis in degrees.
        If NaN, the QWP is not present.

    Returns
    -------
    np.ndarray
        The Jones vector of the resulting polarization state.

    """
    pol = np.array([0.0, 1.0])

    if not np.isnan(hwp_angle):
        pol = jones_hwp(hwp_angle) @ pol

    if not np.isnan(qwp_angle):
        pol = jones_qwp(qwp_angle) @ pol

    return pol
