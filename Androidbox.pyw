import sys
import traceback

from androidbox import cli, native, paths

# "androidbox start Pixel" and the like are commands for the terminal, handled without opening a window. Windows'
# windowed exe has nowhere to print them, so there they go through androidbox-cli.exe instead
if cli.wanted(sys.argv[1:]) and sys.stdout is not None:
    sys.exit(cli.main(sys.argv[1:]))

try:
    from androidbox.ui.app import main
    main()
except Exception:
    paths.DATA.mkdir(parents=True, exist_ok=True)
    paths.CRASH_LOG.write_text(traceback.format_exc())
    native.show_error_box("Androidbox", f"Androidbox crashed. Details are in {paths.CRASH_LOG}")
