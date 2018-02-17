import sublime

import logging
import sys


loggers = []
current_log_level = 'DEBUG'


def load_settings():
    return sublime.load_settings('LLDB.sublime-settings')


def plugin_loaded():
    def on_settings_changed():
        settings = load_settings()
        current_log_level = settings.get('log_level', 'DEBUG')
        for logger in loggers:
            logger.setLevel(current_log_level)

    settings = load_settings()
    settings.add_on_change(__name__, on_settings_changed)

    on_settings_changed()


def get_logger(name):
    """
    Returns a logger for the given name that works in the Sublime Text Console
    """

    logger = logging.getLogger(name)
    if logger not in loggers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            fmt='[%(name)s] %(levelname)s: %(message)s',
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(current_log_level)
        loggers.append(logger)
    return logger

