"""python -m androidbox: the same as opening Androidbox.pyw, which is how it starts on Linux"""
import runpy

from . import paths

runpy.run_path(str(paths.BUNDLE / "Androidbox.pyw"), run_name="__main__")
