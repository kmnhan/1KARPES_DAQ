import numpy as np


def _convert_wp_angle(theta_y: float) -> float:
    return theta_y + 90.0


def jones_hwp(theta_y) -> np.ndarray:
    """Half-wave plate (HWP). Input angle: CW rotation from +y (fast axis)."""
    theta = np.deg2rad(_convert_wp_angle(theta_y))
    c, s = np.cos(2 * theta), np.sin(2 * theta)
    return np.array([[c, s], [s, -c]])


def jones_qwp(theta_y) -> np.ndarray:
    """Quarter-wave plate (QWP). Input angle: CW rotation from +y (fast axis)."""
    theta = np.deg2rad(_convert_wp_angle(theta_y))
    c, s = np.cos(2 * theta), np.sin(2 * theta)
    return (1 / np.sqrt(2)) * np.array([[1 + 1j * c, 1j * s], [1j * s, 1 - 1j * c]])


def jones_polarizer(theta_y) -> np.ndarray:
    """Linear polarizer with transmission axis at theta_y."""
    theta = np.deg2rad(_convert_wp_angle(theta_y))
    c, s = np.cos(theta), np.sin(theta)
    return np.array([[c**2, c * s], [c * s, s**2]])


def get_phase_diff(pol) -> float:
    """Get the phase difference of the polarization vector."""
    Ex, Ey = pol
    # Compute phase difference
    delta = np.angle(Ey) - np.angle(Ex)
    # Normalize delta to [-π, π]
    return (delta + np.pi) % (2 * np.pi) - np.pi


def is_circular(pol, tol=5e-3) -> bool:
    """Check if the polarization is circular."""
    # For circular polarization, the amplitudes should be equal
    # and the phase difference should be ±π/2 (modulo 2π).
    if not np.isclose(np.abs(pol[0]), np.abs(pol[1]), atol=tol):
        return False

    return np.isclose(np.abs(get_phase_diff(pol)), np.pi / 2, atol=tol)


def is_linear(pol, tol=5e-3) -> bool:
    """Check if the polarization is linear."""
    if np.isclose(pol[0], 0, atol=tol) or np.isclose(pol[1], 0, atol=tol):
        return True
    return np.isclose(np.sin(get_phase_diff(pol)), 0, atol=tol)


def get_handedness(pol, tol=5e-3) -> int:
    """Get the handedness of the polarization.

    Returns +1 for left-handed and -1 for right-handed elliptical/circular polarization,
    and 0 for linear polarization.
    """
    if is_linear(pol, tol=tol):
        return 0
    return -int(np.sign(np.sin(get_phase_diff(pol))))


def polarization_info(pol, tol=5e-3) -> str:
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


def polarization_integer(pol, tol=5e-3) -> float:
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

    Assumes initial linear horizontal polarization.

    Parameters
    ----------
    hwp_angle : float
        Angle of the half-wave plate (HWP) fast axis in degrees counterclockwise from
        the +y direction. If NaN, the HWP is not present.
    qwp_angle : float
        Angle of the quarter-wave plate (QWP) fast axis in degrees counterclockwise from
        the +y direction. If NaN, the QWP is not present.

    Returns
    -------
    np.ndarray
        The Jones vector of the resulting polarization state.

    """
    pol = np.array([1.0, 0.0], dtype=complex)

    if not np.isnan(hwp_angle):
        pol = jones_hwp(hwp_angle) @ pol

    if not np.isnan(qwp_angle):
        pol = jones_qwp(qwp_angle) @ pol

    return pol
