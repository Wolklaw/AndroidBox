import traceback

from androidbox import native, paths

try:
    from androidbox.ui.app import main
    main()
except Exception:
    paths.DATA.mkdir(parents=True, exist_ok=True)
    paths.CRASH_LOG.write_text(traceback.format_exc())
    native.show_error_box("Androidbox", f"Androidbox crashed. Details are in {paths.CRASH_LOG}")
