# 1KARPES_DAQ

Data acquisition software for the ultra low temperature ARPES system at the electronic
structure research laboratory at Korea Advanced Institute of Science and Technology
(KAIST).

## User guide

### Starting the software

1. Make sure that the HV rack switch is turned OFF.
2. Power on the DAQ PC (left) and log in with appropriate credentials.
3. Once the DAQ PC is on, power on the logging PC (right) and check if the network drive (D:) is connected.
4. On the logging PC, start the following programs from the desktop (order does not matter):
   - F70H
   - MG15
   - Temperature controller
   - Motion controller

   Check if the programs are running correctly by looking at value updates.
5. Once the programs are running, double click on `Start Servers` in the desktop. In the
   window that appears, click the three `Start Server` buttons.
6. On the DAQ PC, start `SES.exe` from the desktop.
7. In SES, click on `Calibration -> Voltages...`. Close the voltage calibration window
   after making sure that the lens mode is angular and the pass energy is sufficiently
   low.
8. In SES, click on `DA30 -> Control Theta...` and close the control theta window that
   appears.
9. Double click on `Start DAQ` in the desktop. The system is now ready for data
   acquisition.

### Stopping the software

Stopping the software is a reverse process of starting it. Close each program in the
reverse order of starting them. Remember to not close the terminal window that appears
when starting some programs; they will close automatically when the main window of the
program is closed.

### Conducting scans

#### Setting up scans

The DAQ software serves as a front-end for the SES software. All scans *must* be started
with the `Start` button in the DAQ software, not SES. The user will not have to interact
with SES menu items directly.

The slit indicator in the GUI determines the analyzer slit information recorded in the
data file. Remember to set the slit indicator to the correct value when changing the
analyzer slit.

All attributes are recorded when the scan ends.

## Development

### Prerequisites

- Python 3.11 or higher
- Additional dependencies for each program are listed in the `pyproject.toml` file in
  each subdirectory under `src`

### Installation

1. [Install uv](https://docs.astral.sh/uv/getting-started/installation/)

   - On Windows:

     ```bash
     winget install --id=astral-sh.uv  -e
     ```

   - On macOS:

     ```bash
     brew install uv
     ```

2. Clone the repository and navigate to the root directory.

3. Run:

   ```bash
   uv sync --all-extras --dev
   ```

4. Install pre-commit hooks by running `pre-commit install` in the root directory.

### Notes

- Builds must be trigerred manually from the [GitHub Actions page](https://github.com/kmnhan/1KARPES_DAQ/actions).
- When adding or modifying dependencies, use `uv` to manage them. Do not modify the
  `pyproject.toml` files manually.

### Build status

<a href="https://github.com/kmnhan/1KARPES_DAQ/actions/workflows/build_tempcontrol.yml"><img alt="Temperature Controller" src="https://img.shields.io/github/actions/workflow/status/kmnhan/1KARPES_DAQ/build_tempcontrol.yml?label=Temperature%20Controller"></a>

<a href="https://github.com/kmnhan/1KARPES_DAQ/actions/workflows/build_motioncontrol.yml"><img alt="Motion Controller" src="https://img.shields.io/github/actions/workflow/status/kmnhan/1KARPES_DAQ/build_motioncontrol.yml?label=Motion%20Controller"></a>

<a href="https://github.com/kmnhan/1KARPES_DAQ/actions/workflows/build_pyloncam.yml"><img alt="Pylon Camera Viewer" src="https://img.shields.io/github/actions/workflow/status/kmnhan/1KARPES_DAQ/build_pyloncam.yml?label=Pylon%20Camera%20Viewer"></a>

<a href="https://github.com/kmnhan/1KARPES_DAQ/actions/workflows/build_mg15.yml"><img alt="MG15" src="https://img.shields.io/github/actions/workflow/status/kmnhan/1KARPES_DAQ/build_mg15.yml?label=MG15"></a>

<a href="https://github.com/kmnhan/1KARPES_DAQ/actions/workflows/build_f70h.yml"><img alt="F70H" src="https://img.shields.io/github/actions/workflow/status/kmnhan/1KARPES_DAQ/build_f70h.yml?label=F70H"></a>

<a href="https://github.com/kmnhan/1KARPES_DAQ/actions/workflows/build_logviewer.yml"><img alt="Log Viewer" src="https://img.shields.io/github/actions/workflow/status/kmnhan/1KARPES_DAQ/build_logviewer.yml?label=Log%20Viewer"></a>

<a href="https://github.com/kmnhan/1KARPES_DAQ/actions/workflows/build_webcam.yml"><img alt="Webcam Viewer" src="https://img.shields.io/github/actions/workflow/status/kmnhan/1KARPES_DAQ/build_webcam.yml?label=Webcam%20Viewer"></a>
