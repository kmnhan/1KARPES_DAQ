# 1KARPES_DAQ

Data acquisition software for the ultra low temperature ARPES system at the electronic
structure research laboratory at Korea Advanced Institute of Science and Technology
(KAIST).

## Prerequisites

- Python 3.11 or higher
- Additional dependencies for each program are listed in the `pyproject.toml` file in
  each subdirectory under `src`

## Development

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

## Build status

<a href="https://github.com/kmnhan/1KARPES_DAQ/actions/workflows/build_tempcontrol.yml"><img alt="Temperature Controller" src="https://img.shields.io/github/actions/workflow/status/kmnhan/1KARPES_DAQ/build_tempcontrol.yml?label=Temperature%20Controller"></a>

<a href="https://github.com/kmnhan/1KARPES_DAQ/actions/workflows/build_motioncontrol.yml"><img alt="Motion Controller" src="https://img.shields.io/github/actions/workflow/status/kmnhan/1KARPES_DAQ/build_motioncontrol.yml?label=Motion%20Controller"></a>

<a href="https://github.com/kmnhan/1KARPES_DAQ/actions/workflows/build_pyloncam.yml"><img alt="Pylon Camera Viewer" src="https://img.shields.io/github/actions/workflow/status/kmnhan/1KARPES_DAQ/build_pyloncam.yml?label=Pylon%20Camera%20Viewer"></a>

<a href="https://github.com/kmnhan/1KARPES_DAQ/actions/workflows/build_mg15.yml"><img alt="MG15" src="https://img.shields.io/github/actions/workflow/status/kmnhan/1KARPES_DAQ/build_mg15.yml?label=MG15"></a>

<a href="https://github.com/kmnhan/1KARPES_DAQ/actions/workflows/build_f70h.yml"><img alt="F70H" src="https://img.shields.io/github/actions/workflow/status/kmnhan/1KARPES_DAQ/build_f70h.yml?label=F70H"></a>

<a href="https://github.com/kmnhan/1KARPES_DAQ/actions/workflows/build_logviewer.yml"><img alt="Log Viewer" src="https://img.shields.io/github/actions/workflow/status/kmnhan/1KARPES_DAQ/build_logviewer.yml?label=Log%20Viewer"></a>

<a href="https://github.com/kmnhan/1KARPES_DAQ/actions/workflows/build_webcam.yml"><img alt="Webcam Viewer" src="https://img.shields.io/github/actions/workflow/status/kmnhan/1KARPES_DAQ/build_webcam.yml?label=Webcam%20Viewer"></a>
