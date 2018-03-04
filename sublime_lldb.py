import json
import os
import sys

current_directory = os.path.dirname(os.path.realpath(__file__))
sys.path.append(current_directory)

import sublime
import sublime_plugin

from lldbserver.server import LldbServer


LLDB_SERVER = None
PROMPT = '(lldb) '
TARGET_RUN_POINTER_MAP = {}


class EventListenerDispatcher(object):
    """ Makes sure listener calls are happening on the main thread """

    def __init__(self, proxy):
        self.proxy = proxy

    def __getattr__(self, name):
       return lambda **args: sublime.set_timeout(
            lambda: getattr(self.proxy, name)(**args), 0)


class LldbRun(sublime_plugin.WindowCommand):

    def run(self, executable_path):
        global LLDB_SERVER
        self.create_console()

        if LLDB_SERVER is not None:
            LLDB_SERVER.kill()

        settings = sublime.load_settings('lldb.sublime-settings')
        listener = EventListenerDispatcher(self)
        LLDB_SERVER = LldbServer(
            settings.get('python_binary', 'python'),
            settings.get('lldb_python_lib_directory', None),
            listener,
        )
        lldb_service = LLDB_SERVER.lldb_service
        target_name = os.path.basename(executable_path)
        self.console_log('Current executable set to %r' % target_name)
        lldb_service.create_target(executable_path=executable_path)
        self.set_breakpoints(lldb_service)
        lldb_service.target_launch()

    def set_breakpoints(self, lldb_service):
        for file, breakpoints in load_breakpoints(self.window).items():
            for line in breakpoints:
                lldb_service.target_set_breakpoint(file=file, line=line)

    def create_console(self):
        self.console = self.window.create_output_panel('lldb')
        self.console.set_name('lldb-console')
        self.console.set_syntax_file('lldb-console.sublime-syntax')
        self.console.settings().set('line_numbers', False)
        self.console.set_scratch(True)
        self.window.run_command('show_panel', args={'panel': 'output.lldb'})

    def on_process_state(self, state):
        if state == 'stopped':
            self.console.run_command('lldb_show_prompt')
        elif state == 'exited':
            self.console.run_command('lldb_hide_prompt')

            for view in self.window.views():
                view.erase_regions('run_pointer')

        self.console_log('Process state changed %r' % state)

    def on_location(self, line_entry):
        self.jump_to(line_entry)

    def on_process_std_out(self, output):
        self.console_log(output)

    def on_process_std_err(self, output):
        self.console_log(output)

    def on_command_finished(self, output, success):
        self.console_log(output)
        self.console.run_command('lldb_show_prompt')

    def console_log(self, message):
        self.console.run_command('lldb_append_text', {'text': message})

    def jump_to(self, line_entry):
        path = os.path.join(line_entry['directory'], line_entry['filename'])
        view = self.window.open_file(
            '%s:%s' % (path, line_entry['line']),
            sublime.ENCODED_POSITION,
        )

        if view.is_loading():
            TARGET_RUN_POINTER_MAP[view.id()] = line_entry['line']
        else:
            set_run_pointer(view, line_entry['line'])


class LldbKill(sublime_plugin.WindowCommand):

    def run(self):
        LLDB_SERVER.lldb_service.process_kill()

    def is_enabled(self):
        return LLDB_SERVER is not None


def set_run_pointer(view, line):
    region = view.line(view.text_point(line - 1, 0))
    view.add_regions(
        'run_pointer',
        regions=[region],
        scope='comment',
        flags=sublime.DRAW_NO_FILL,
    )


def set_breakpoints_for_view(view, breakpoints):
    regions = [
        view.line(view.text_point(line, 0))
        for line in breakpoints
    ]

    view.erase_regions('breakpoint')
    view.add_regions(
        'breakpoint',
        regions,
        'breakpoint',
        'dot',
        sublime.HIDDEN,
    )


def get_breakpoints(view):
    regions = view.get_regions('breakpoint')
    return [view.rowcol(region.a)[0] for region in regions]


def breakpoint_settings_path(window):
    project_path = window.extract_variables().get('project_path')
    return os.path.join(
        project_path,
        '.lldb-breakpoints',
    )


def save_breakpoints(view):
    breakpoints_dict = load_breakpoints(view.window())
    breakpoints = get_breakpoints(view)
    if breakpoints:
        breakpoints_dict[view.file_name()] = breakpoints
    else:
        breakpoints_dict.pop(view.file_name())

    with open(breakpoint_settings_path(view.window()), 'w') as f:
        return json.dump(breakpoints_dict, f)


def load_breakpoints(window):
    try:
        with open(breakpoint_settings_path(window), 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


class LldbToggleBreakpoint(sublime_plugin.TextCommand):

    def run(self, edit):
        selection = self.view.sel()[-1]
        line = self.view.rowcol(selection.a)[0]
        breakpoints = set(get_breakpoints(self.view))

        if line in breakpoints:
            breakpoints.remove(line)
            if LLDB_SERVER is not None:
                LLDB_SERVER.lldb_service.target_delete_breakpoint(
                    file=self.view.file_name(),
                    line=line,
                )
        else:
            breakpoints.add(line)
            if LLDB_SERVER is not None:
                LLDB_SERVER.lldb_service.target_set_breakpoint(
                    file=self.view.file_name(),
                    line=line,
                )

        set_breakpoints_for_view(self.view, breakpoints)
        save_breakpoints(self.view)


class LldbIndicatorsListener(sublime_plugin.EventListener):

    def on_load_async(self, view):
        self._update_breakpoints(view)
        self._show_pending_run_pointer(view)

    def on_activated_async(self, view):
        self._update_breakpoints(view)

    def _update_breakpoints(self, view):
        if view.window():
            breakpoints = load_breakpoints(
                view.window()).get(view.file_name(), [])
            set_breakpoints_for_view(view, breakpoints)

    def _show_pending_run_pointer(self, view):
        run_pointer_line = TARGET_RUN_POINTER_MAP.get(view.id(), None)
        if run_pointer_line is not None:
            set_run_pointer(view, run_pointer_line)
            del TARGET_RUN_POINTER_MAP[view.id()]


class LldbAppendText(sublime_plugin.TextCommand):

    def run(self, edit, text):
        if not text.endswith('\n'):
            text = text + '\n'

        last_line_region = self.view.line(self.view.size())
        line = self.view.substr(last_line_region)
        if line == PROMPT:
            row, col = self.view.rowcol(self.view.size())
            insert_point = self.view.text_point(row, 0)
        else:
            insert_point = self.view.size()

        self.view.insert(edit, insert_point, text)
        self.view.show(self.view.size())
        self.view.window().focus_view(self.view)


class LldbShowPrompt(sublime_plugin.TextCommand):

    def run(self, edit):
        last_line_region = self.view.line(self.view.size())
        line = self.view.substr(last_line_region)
        if line != PROMPT:
            self.view.insert(edit, self.view.size(), PROMPT)
            self.view.show(self.view.size())
            end_pos = self.view.size()
            self.view.sel().add(sublime.Region(end_pos, end_pos))


class LldbHidePrompt(sublime_plugin.TextCommand):

    def run(self, edit):
        last_line_region = self.view.line(self.view.size())
        line = self.view.substr(last_line_region)
        if line == PROMPT:
            self.view.erase(edit, last_line_region)


class LldbConsoleListener(sublime_plugin.EventListener):

    def on_modified(self, view):
        if view.name() == 'lldb-console':
            last_line_region = view.line(view.size())
            line = view.substr(last_line_region)
            if not line:
                last_line_region = view.line(view.size() - 1)
                line = view.substr(last_line_region)
                if line.startswith(PROMPT):
                    command = line[7:]
                    LLDB_SERVER.lldb_service.handle_command(input=command)
