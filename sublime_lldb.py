import sys
import os

current_directory = os.path.dirname(os.path.realpath(__file__))
sys.path.append(current_directory)

import sublime
import sublime_plugin

from lldbserver.server import LldbServer


LLDB_SERVER = None
PROMPT = '(lldb) '


class EventListenerDispatcher(object):

    def __init__(self, proxy):
        self.proxy = proxy

    def on_process_state_changed(self, state):
        sublime.set_timeout(
            lambda: self.proxy.on_process_state_changed(state), 0)

    def on_process_std_out(self, output):
        sublime.set_timeout(
            lambda: self.proxy.on_process_std_out(output), 0)

    def on_process_std_err(self, output):
        sublime.set_timeout(
            lambda: self.proxy.on_process_std_err(output), 0)

    def on_location_changed(self, location):
        sublime.set_timeout(
            lambda: self.proxy.on_location_changed(location), 0)

    def on_command_output(self, output):
        sublime.set_timeout(
            lambda: self.proxy.on_command_output(output), 0)

    def on_error(self, output):
        sublime.set_timeout(
            lambda: self.proxy.on_error(output), 0)


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
        self.log('Current executable set to %r' % target_name)
        lldb_service.create_target(executable_path)
        self.set_breakpoints(lldb_service)
        lldb_service.target_launch()

    def set_breakpoints(self, lldb_service):
        for file, breakpoints in load_breakpoints(self.window).items():
            for line in breakpoints:
                lldb_service.target_set_breakpoint(file, line)

    def create_console(self):
        self.console = self.window.create_output_panel('lldb')
        self.console.set_name('lldb-console')
        self.console.set_syntax_file('lldb-console.sublime-syntax')
        self.console.settings().set('line_numbers', False)
        self.console.set_scratch(True)

    def on_process_state_changed(self, state):
        if state == 'exited':
            self.console.run_command('lldb_hide_prompt')

            for view in self.window.views():
                view.erase_regions('run_pointer')

        self.log('Process state changed %r' % state)

    def on_location_changed(self, location):
        self.jump_to(location)
        self.console.run_command('lldb_show_prompt')

    def on_process_std_out(self, output):
        self.log(output)

    def on_process_std_err(self, output):
        self.log(output)

    def on_command_output(self, output):
        self.log(output)

    def on_error(self, message):
        self.log(message)

    def log(self, message):
        self.console.run_command('lldb_append_text', {'text': message})
        self.window.run_command('show_panel', args={'panel': 'output.lldb'})
        self.window.focus_view(self.window.find_output_panel('lldb'))

    def jump_to(self, line_entry):
        path = os.path.join(line_entry['directory'], line_entry['filename'])
        view = self.window.open_file(
            '%s:%s' % (path, line_entry['line']),
            sublime.ENCODED_POSITION,
        )

        location = view.line(view.text_point(line_entry['line'] - 1, 0))
        view.add_regions(
            'run_pointer',
            regions=[location],
            scope='comment',
            flags=sublime.DRAW_NO_FILL,
        )


class LldbKill(sublime_plugin.WindowCommand):

    def run(self):
        LLDB_SERVER.lldb_service.process_destroy()


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


def save_breakpoints(view):
    project_data = view.window().project_data()
    settings = project_data.setdefault('settings', {})
    sublime_lldb_settings = settings.setdefault('sublime-lldb', {})
    breakpoints_dict = sublime_lldb_settings.setdefault('breakpoints', {})
    breakpoints = get_breakpoints(view)
    if breakpoints:
        breakpoints_dict[view.file_name()] = breakpoints
    else:
        breakpoints_dict.pop(view.file_name())
    view.window().set_project_data(project_data)


def load_breakpoints(window):
    project_data = window.project_data()
    settings = project_data.get('settings', {})
    sublime_lldb_settings = settings.get('sublime-lldb', {})
    return sublime_lldb_settings.get('breakpoints', {})


class LldbToggleBreakpoint(sublime_plugin.TextCommand):

    def run(self, edit):
        selection = self.view.sel()[-1]
        line = self.view.rowcol(selection.a)[0]
        breakpoints = set(get_breakpoints(self.view))

        if line in breakpoints:
            breakpoints.remove(line)
        else:
            breakpoints.add(line)

        set_breakpoints_for_view(self.view, breakpoints)
        save_breakpoints(self.view)


class LldbBreakpointListener(sublime_plugin.EventListener):

    def on_activated(self, view):
        breakpoints = load_breakpoints(view.window()).get(view.file_name(), [])
        set_breakpoints_for_view(view, breakpoints)



def find(seq, func):
    """Return first item in sequence where f(item) == True."""

    for item in seq:
        if func(item):
            return item


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
                    self.run_command(view, command)

    def run_command(self, view, command):
        LLDB_SERVER.lldb_service.handle_command(command)
        view.run_command('lldb_show_prompt')
