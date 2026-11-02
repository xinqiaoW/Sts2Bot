"""Compatibility command for old patch instructions; use install_bot_update.py."""
if __package__:
    from .install_bot_update import SOURCES, CONFIGS, NATIVE, install, main
else:
    from install_bot_update import SOURCES, CONFIGS, NATIVE, install, main


if __name__ == '__main__':
    main()
