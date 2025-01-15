# 1KARPES_DAQ

Data acquisition software for the ultra low temperature ARPES system at the electronic
structure research laboratory at Korea Advanced Institute of Science and Technology
(KAIST).

## Prerequisites

- Python 3.11 or higher
- Additional dependencies for each program are listed in the `requirements.txt` file in
  each subdirectory under `packages/`

## Development

1. Clone the repository and navigate to the root directory.

2. Setup a mamba environment:
   ```bash
   mamba env create -f environment.yml
   mamba activate daq
   ```
   This will create and activate a new environment called `daq` with all the necessary dependencies.

4. Install pre-commit hooks by running `pre-commit install` in the root directory.

### Notes
- Builds must be trigerred manually from the [GitHub Actions page](https://github.com/kmnhan/1KARPES_DAQ/actions).
- If you add or modify any dependencies, make sure to update the `requirements.txt` file
  in the corresponding subdirectory and the `environment.yml` file in the root
  directory


## Build status

<a href="https://github.com/kmnhan/1KARPES_DAQ/actions/workflows/build_tempcontroller.yml"><img alt="Temperature Controller" src="https://img.shields.io/github/actions/workflow/status/kmnhan/1KARPES_DAQ/build_tempcontroller.yml?label=Temperature%20Controller"></a>

<a href="https://github.com/kmnhan/1KARPES_DAQ/actions/workflows/build_motioncontrol.yml"><img alt="Motion Controller" src="https://img.shields.io/github/actions/workflow/status/kmnhan/1KARPES_DAQ/build_motioncontrol.yml?label=Motion%20Controller"></a>

<a href="https://github.com/kmnhan/1KARPES_DAQ/actions/workflows/build_pyloncam.yml"><img alt="Pylon Camera Viewer" src="https://img.shields.io/github/actions/workflow/status/kmnhan/1KARPES_DAQ/build_pyloncam.yml?label=Pylon%20Camera%20Viewer"></a>

<a href="https://github.com/kmnhan/1KARPES_DAQ/actions/workflows/build_mg15.yml"><img alt="MG15" src="https://img.shields.io/github/actions/workflow/status/kmnhan/1KARPES_DAQ/build_mg15.yml?label=MG15"></a>

<a href="https://github.com/kmnhan/1KARPES_DAQ/actions/workflows/build_f70h.yml"><img alt="F70H" src="https://img.shields.io/github/actions/workflow/status/kmnhan/1KARPES_DAQ/build_f70h.yml?label=F70H"></a>

<a href="https://github.com/kmnhan/1KARPES_DAQ/actions/workflows/build_logviewer.yml"><img alt="Log Viewer" src="https://img.shields.io/github/actions/workflow/status/kmnhan/1KARPES_DAQ/build_logviewer.yml?label=Log%20Viewer"></a>

<a href="https://github.com/kmnhan/1KARPES_DAQ/actions/workflows/build_webcam.yml"><img alt="Webcam Viewer" src="https://img.shields.io/github/actions/workflow/status/kmnhan/1KARPES_DAQ/build_webcam.yml?label=Webcam%20Viewer"></a>
