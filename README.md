# Quick Start

Ape compiler plugin around [the Starknet Cairo language](https://github.com/starkware-libs/cairo).

## Dependencies

- [python3](https://www.python.org/downloads) version 3.9 up to 3.11.

## Requirements

- **(Recommended)** If you have Scarb project, please install [Scarb](https://docs.swmansion.com/scarb/download.html) .

```shell
# Install via quick installation script
curl --proto '=https' --tlsv1.2 -sSf https://docs.swmansion.com/scarb/install.sh | sh
```

  or

  ```shell
  # Install via asdf version manager
  asdf plugin add scarb
  asdf install scarb latest
  asdf global scarb latest
  ```

## Installation

### via `pip`

You can install the latest release via [`pip`](https://pypi.org/project/pip/):

```bash
pip install ape-cairo
```

### via `setuptools`

You can clone the repository and use [`setuptools`](https://github.com/pypa/setuptools) for the most up-to-date version:

```bash
git clone https://github.com/ApeWorX/ape-cairo.git
cd ape-cairo
python3 setup.py install
```

## Quick Usage

`ape-cairo` can compile Scarb projects that defines `Scarb.toml` file.

### ✿ Scarb Projects

Scarb binary is required to compile Scarb projects. Please add it to your $PATH if you have not done so. 

#### Using the Compiler

In a project directory where there are `.cairo` files in your `contracts/` directory, run the `compile` command:

```bash
ape compile
```

It should compile your Cairo contracts. You can find the compiled contract artifacts (Sierra/Casm) in the `.build/` directory.

> You can also get debug outputs by running the command with the `-v DEBUG` flag.
>
> ```shell
> ape compile -v DEBUG
> ```

### Examples

See the [examples](tests/projects/) directory for examples.

## Development

Please see the [contributing guide](CONTRIBUTING.md) to learn more how to contribute to this project.
Comments, questions, criticisms and pull requests are welcomed.
