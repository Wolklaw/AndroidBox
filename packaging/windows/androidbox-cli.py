# The console program behind the `androidbox` command on Windows. Androidbox.exe is a windowed program, which
# Windows gives no console to print to, so the command line needs an exe of its own in the same folder
import sys

from androidbox import cli

sys.exit(cli.main())
