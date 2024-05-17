from ape import plugins

from ._utils import Extension
from .compiler import CairoCompiler, CairoConfig


@plugins.register(plugins.Config)
def config_class():
    return CairoConfig


@plugins.register(plugins.CompilerPlugin)
def register_compiler():
    return (Extension.CAIRO.value,), CairoCompiler
