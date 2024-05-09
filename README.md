# 1KARPES_DAQ

Data acquisition software for the ultra low temperature ARPES system at the electronic
structure research laboratory at Korea Advanced Institute of Science and Technology
(KAIST).

## Prerequisites

- Python 3.11 or higher
- Additional dependencies for each program are listed in the `requirements.txt` file in
  each subdirectory under `src/`

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

<img alt="Temperature Controller" src="https://img.shields.io/github/actions/workflow/status/kmnhan/1KARPES_DAQ/build_tempcontroller.yml?label=Temperature%20Controller&link=https%3A%2F%2Fgithub.com%2Fkmnhan%2F1KARPES_DAQ%2Factions%2Fworkflows%2Fbuild_tempcontroller.yml">

<img alt="Motion Controller" src="https://img.shields.io/github/actions/workflow/status/kmnhan/1KARPES_DAQ/build_motioncontrol.yml?label=Motion%20Controller&link=https%3A%2F%2Fgithub.com%2Fkmnhan%2F1KARPES_DAQ%2Factions%2Fworkflows%2Fbuild_motioncontrol.yml">

<img alt="Pylon Camera Viewer" src="https://img.shields.io/github/actions/workflow/status/kmnhan/1KARPES_DAQ/build_pyloncam.yml?label=Pylon%20Camera%20Viewer&link=https%3A%2F%2Fgithub.com%2Fkmnhan%2F1KARPES_DAQ%2Factions%2Fworkflows%2Fbuild_pyloncam.yml">

<img alt="MG15" src="https://img.shields.io/github/actions/workflow/status/kmnhan/1KARPES_DAQ/build_mg15.yml?label=MG15&link=https%3A%2F%2Fgithub.com%2Fkmnhan%2F1KARPES_DAQ%2Factions%2Fworkflows%2Fbuild_mg15.yml">

<img alt="Log Viewer" src="https://img.shields.io/github/actions/workflow/status/kmnhan/1KARPES_DAQ/build_logviewer.yml?label=Log%20Viewer&link=https%3A%2F%2Fgithub.com%2Fkmnhan%2F1KARPES_DAQ%2Factions%2Fworkflows%2Fbuild_logviewer.yml">

<img alt="Webcam Viewer" src="https://img.shields.io/github/actions/workflow/status/kmnhan/1KARPES_DAQ/build_webcam.yml?label=Webcam%20Viewer&link=https%3A%2F%2Fgithub.com%2Fkmnhan%2F1KARPES_DAQ%2Factions%2Fworkflows%2Fbuild_webcam.yml">
