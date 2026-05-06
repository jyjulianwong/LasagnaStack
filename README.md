# LasagnaStack

## Get started with development

1. Clone the repository.

```bash
git clone https://github.com/jyjulianwong/LasagnaStack.git
```

2. Verify that you have a compatible Python version installed on your machine.
```bash
python --version
```

3. Install [uv](https://github.com/astral-sh/uv) (used as the package manager for this project).

4. Install the development dependencies.
```bash
cd LasagnaStack/
uv sync --all-groups
uv run pre-commit install
```

## Get started with Jupyter notebooks

1. Once the above setup is complete, set up a Python kernel.
```bash
source .venv/bin/activate
python -m ipykernel install --user --name=lasagnastack
```

2. Refer to the following common commands.
```bash
jupyter kernelspec list
jupyter kernelspec uninstall lasagnastack
```

3. Start the Jupyter server.
```bash
jupyter lab
```