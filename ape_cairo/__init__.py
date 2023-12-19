from ape import plugins
from .compiler import CairoCompiler, CairoConfig
from ._utils import Extension


@plugins.register(plugins.Config)
def config_class():
    return CairoConfig


@plugins.register(plugins.CompilerPlugin)
def register_compiler():
    return (Extension.CAIRO.value,), CairoCompiler
