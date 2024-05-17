# Quick Start

Ape compiler plugin around [the Starknet Cairo language](https://github.com/starkware-libs/cairo).

## Dependencies

- [python3](https://www.python.org/downloads) version 3.8 up to 3.11.

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

- If you have a single Cairo contract or a package that defines `cairo_project.toml` file, please install [Cairo](https://github.com/starkware-libs/cairo)

  First, you need to install Rust. You can do this by running the following command:

  ```shell
  rustup override set stable && rustup update
  ```

  Then, you can install Cairo by running the following command:

  ```shell
  git clone https://github.com/starkware-libs/cairo my/cairo/path
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

`ape-cairo` can compile,

- Scarb projects
- Single Cairo contracts
- Packages (crates) that define `cairo_project.toml` file.

### ✿ Scarb Projects

Scarb binary is required to compile Scarb projects. Please add it to your $PATH if you have not done so.

Now, when compiling, Ape will use the command `scarb build`. You can specify the Scarb manifest file (Scarb.toml) in your `ape-config.yaml` file:

```yaml
cairo:
  scarb_manifest: /Users/home/path/to/scarb/project/Scarb.toml
```

### ❂ Other Cairo Projects

[Cairo compiler binaries](https://github.com/starkware-libs/cairo?tab=readme-ov-file#compiling-starknet-contracts) are required to compile other Cairo projects.

Please add them to your $PATH. You can verify them by doing:

```bash
which sierra-compile
```

and

```shell
which starknet-compile
```

or you can specify the Cairo manifest path in your `ape-config.yaml` file:

```yaml
cairo:
  cairo_manifest: /Users/home/path/to/cairo/Cargo.toml
```

If you have a package that defines `cairo_project.toml` file, you can also specify the package manifest path in your `ape-config.yaml` file, if it is not in the directory where `ape-config.yaml` is located.

```yaml
cairo:
  package_manifest: /Users/home/path/to/package/cairo_project.toml
```

## ★ Using the Compiler

In a project directory where there are `.cairo` files in your `contracts/` directory, run the `compile` command:

```bash
ape compile
```

It should compile your Cairo contracts. You can find the compiled contract artifacts (Sierra/Casm) in the `.build/` folder.

> You can also get debug outputs by running the command with the `--debug` flag.
>
> ```shell
> ape compile -v DEBUG
> ```

### Manage Cairo Project Dependencies

`ape-cairo` can manage your Cairo project dependencies. See [Ape documentation](https://docs.apeworx.io/ape/stable/userguides/dependencies.html). But, it is recommended to use Scarb for managing dependencies in Scarb projects.

### Ape Config Parameters

- `dependencies`: A list of dependencies that the project depends on. Optional.
- `cairo_manifest`: The path to the Cairo compiler manifest file. Required if you didn't add binaries (sierra-compile, starknet-compile) to your $PATH.
- `scarb_manifest`: The path to the Scarb project manifest file. Required if you are compiling a Scarb project.
- `package_manifest`: The path to the package manifest file that defines the Cairo project. Required if you are compiling multiple Cairo contracts in a package and the manifest file is not in the directory where `ape-config.yaml` is located.

## Development

Please see the [contributing guide](CONTRIBUTING.md) to learn more how to contribute to this project.
Comments, questions, criticisms and pull requests are welcomed.
