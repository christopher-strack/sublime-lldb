import json
import os
import sys

from contextlib import contextmanager

current_directory = os.path.dirname(os.path.realpath(__file__))
sys.path.append(current_directory)

import sublime
import sublime_plugin

from lldbserver.server import LldbServer


PROMPT = '(lldb) '

lldb_server = None
target_run_pointer_map = {}


def plugin_loaded():
    sublime.set_timeout_async(set_all_breakpoints, 0)


class EventListenerDispatcher(object):
    """ Makes sure listener calls are happening on the main thread """

    def __init__(self, proxy):
        self.proxy = proxy

    def __getattr__(self, name):
       return lambda **args: sublime.set_timeout(
            lambda: getattr(self.proxy, name)(**args), 0)


class LldbRun(sublime_plugin.WindowCommand):

    def run(self, executable_path=None, arguments=[], environment=None):
        if executable_path is None:
            self.window.show_input_panel(
                'Enter executable path',
                '',
                lambda input: self.start_server(input, arguments, environment),
                None,
                None,
            )
        else:
            self.start_server(executable_path, arguments, environment)

    def start_server(self, executable_path, arguments, environment):
        global lldb_server

        self.state = None
        self.create_console()

        if lldb_server is not None:
            lldb_server.process.kill()

        settings = sublime.load_settings('sublime-lldb.sublime-settings')
        listener = EventListenerDispatcher(self)
        lldb_server = LldbServer(
            settings.get('python_binary', 'python'),
            settings.get('lldb_python_lib_directory', None),
            listener,
            listener,
        )
        lldb_service = lldb_server.lldb_service
        target_name = os.path.basename(executable_path)
        self.console_log('Current executable set to %r' % target_name)
        lldb_service.create_target(executable_path=executable_path)
        self.set_breakpoints(lldb_service)
        lldb_service.target_launch(
            arguments=arguments,
            environment=environment,
        )

    def set_breakpoints(self, lldb_service):
        for file, breakpoints in load_breakpoints(self.window).items():
            for line in breakpoints:
                lldb_service.target_set_breakpoint(file=file, line=line + 1)

    def create_console(self):
        self.console = self.window.create_output_panel('lldb')
        self.console.set_name('lldb-console')
        self.console.set_syntax_file('lldb-console.sublime-syntax')
        self.console.settings().set('line_numbers', False)
        self.console.set_scratch(True)
        self.console.set_read_only(True)
        self.window.run_command('show_panel', args={'panel': 'output.lldb'})

    def on_process_state(self, state):
        if state == 'stopped':
            self.console.run_command('lldb_console_show_prompt')
        elif state == 'exited':
            self.console.run_command('lldb_console_hide_prompt')
            remove_run_pointer(self.window)

        self.state = state
        self.console_log('Process state changed %r' % state)

    def on_location(self, line_entry):
        self.jump_to(line_entry)

    def on_process_std_out(self, output):
        self.console_log(output)

    def on_process_std_err(self, output):
        self.console_log(output)

    def on_command_finished(self, output, success):
        self.console_log(output)

        if self.state == 'stopped':
            self.console.run_command('lldb_console_show_prompt')

    def on_server_stopped(self):
        global lldb_server
        lldb_server = None

    def on_error(self, error):
        self.console_log(error)

    def console_log(self, message):
        self.console.run_command('lldb_console_append_text', {'text': message})

    def jump_to(self, line_entry):
        path = os.path.join(line_entry['directory'], line_entry['filename'])
        view = self.window.open_file(
            '%s:%s' % (path, line_entry['line']),
            sublime.ENCODED_POSITION,
        )

        if view.is_loading():
            target_run_pointer_map[view.id()] = line_entry['line']
        else:
            set_run_pointer(view, line_entry['line'])


class LldbQuickRun(sublime_plugin.WindowCommand):

    def is_enabled(self):
        settings = sublime.load_settings('sublime-lldb.sublime-settings')
        return len(settings.get('quick_targets', [])) > 0

    def run(self):
        settings = sublime.load_settings('sublime-lldb.sublime-settings')
        targets = settings.get('quick_targets', [])
        target_names = [
            target['executable_path']
            for target in targets if target.get('executable_path', None)
        ]
        self.window.show_quick_panel(
            target_names,
            lambda index: self.run_target(targets[index])
            if index != -1 else None)

    def run_target(self, target):
        self.window.run_command('lldb_run', args=target)


class LldbKill(sublime_plugin.WindowCommand):

    def run(self):
        lldb_server.lldb_service.process_kill()

    def is_enabled(self):
        return lldb_server is not None


def remove_run_pointer(window):
    for view in window.views():
        view.erase_regions('run_pointer')


def set_run_pointer(view, line):
    remove_run_pointer(view.window())
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


def set_all_breakpoints():
    window = sublime.active_window()
    breakpoints = load_breakpoints(window)

    for view in window.views():
        set_breakpoints_for_view(view, breakpoints.get(view.file_name(), []))


def get_breakpoints(view):
    regions = view.get_regions('breakpoint')
    return [view.rowcol(region.a)[0] for region in regions]


def breakpoint_settings_path(window):
    project_path = window.extract_variables().get('project_path')
    if project_path is None:
        project_path = os.path.expanduser('~')

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
            if lldb_server is not None:
                lldb_server.lldb_service.target_delete_breakpoint(
                    file=self.view.file_name(),
                    line=line + 1,
                )
        else:
            breakpoints.add(line)
            if lldb_server is not None:
                lldb_server.lldb_service.target_set_breakpoint(
                    file=self.view.file_name(),
                    line=line + 1,
                )

        set_breakpoints_for_view(self.view, breakpoints)
        save_breakpoints(self.view)


class LldbIndicatorsListener(sublime_plugin.EventListener):

    def on_load(self, view):
        self._show_pending_run_pointer(view)

    def on_load_async(self, view):
        self._update_breakpoints(view)

    def on_activated_async(self, view):
        self._update_breakpoints(view)

    def _update_breakpoints(self, view):
        if view.window():
            breakpoints = load_breakpoints(
                view.window()).get(view.file_name(), [])
            set_breakpoints_for_view(view, breakpoints)

    def _show_pending_run_pointer(self, view):
        run_pointer_line = target_run_pointer_map.get(view.id(), None)
        if run_pointer_line is not None:
            set_run_pointer(view, run_pointer_line)
            del target_run_pointer_map[view.id()]


def last_line(view):
    last_line_region = view.line(view.size())
    return view.substr(last_line_region), last_line_region


def extract_command(view):
    line, _ = last_line(view)
    if line.startswith(PROMPT):
        return line[len(PROMPT):]


def selection_inside_input_region(view, proper_subset):
    line, input_region = last_line(view)
    if line.startswith(PROMPT):
        input_region.a += len(PROMPT)

        if not proper_subset:
            input_region.a += 1
            input_region.b += 1

        for region in view.sel():
            if not input_region.contains(region):
                return False
        return True
    return False


class LldbConsoleShow(sublime_plugin.WindowCommand):

    def is_enabled(self):
        return self.window.find_output_panel('lldb') is not None and \
            self.window.active_panel() is None

    def run(self):
        console = self.window.find_output_panel('lldb')
        if console:
            self.window.run_command('show_panel', args={'panel': 'output.lldb'})
            console.show(console.size())
            self.window.focus_view(console)


class LldbConsoleHide(sublime_plugin.WindowCommand):

    def is_enabled(self):
        return self.window.find_output_panel('lldb') is not None and \
            self.window.active_panel() == 'output.lldb'

    def run(self):
        self.window.run_command('hide_panel', args={'panel': 'output.lldb'})


@contextmanager
def writeable_view(view):
    read_only = view.is_read_only()
    view.set_read_only(False)
    yield
    view.set_read_only(read_only)


class LldbConsoleAppendText(sublime_plugin.TextCommand):

    def run(self, edit, text):
        if not text.endswith('\n'):
            text = text + '\n'

        line, _ = last_line(self.view)
        if line == PROMPT:
            row, _ = self.view.rowcol(self.view.size())
            insert_point = self.view.text_point(row, 0)
        else:
            insert_point = self.view.size()

        with writeable_view(self.view):
            self.view.insert(edit, insert_point, text)


class LldbConsoleShowPrompt(sublime_plugin.TextCommand):

    def run(self, edit):
        line, _ = last_line(self.view)
        if line != PROMPT:
            self.view.set_read_only(False)
            self.view.insert(edit, self.view.size(), PROMPT)
            end_pos = self.view.size()
            self.view.sel().add(sublime.Region(end_pos, end_pos))
            self.view.show(self.view.size())
            self.view.window().focus_view(self.view)


class LldbConsoleHidePrompt(sublime_plugin.TextCommand):

    def run(self, edit):
        line, region = last_line(self.view)
        if line == PROMPT:
            self.view.erase(edit, region)
            self.view.set_read_only(True)


class LldbConsoleListener(sublime_plugin.EventListener):

    def on_selection_modified(self, view):
        if view.name() == 'lldb-console':
            line, _ = last_line(view)
            view.set_read_only(
                not selection_inside_input_region(view, proper_subset=True))

    def on_text_command(self, view, command_name, args):
        result = None

        if view.name() == 'lldb-console':
            if command_name in ('left_delete', 'delete_word'):
                if not selection_inside_input_region(view, proper_subset=False):
                    result = 'noop'
            elif command_name == 'cut':
                if not selection_inside_input_region(view, proper_subset=True):
                    result = 'noop'
                else:
                    if all([r.empty() for r in view.sel()]):
                        result = 'noop'
            elif command_name == 'insert' and args['characters'] == '\n':
                self.on_console_command_entered(view)

        return result

    def on_console_command_entered(self, view):
        command = extract_command(view)
        if command is not None and lldb_server is not None:
            lldb_server.lldb_service.handle_command(input=command)

    def on_query_completions(self, view, prefix, locations):
        if view.name() == 'lldb-console':
            command = extract_command(view)
            if command is not None and lldb_server is not None:
                _, col = view.rowcol(view.sel()[0].a)
                matches = lldb_server.lldb_service.handle_completion(
                    current_line=command, cursor_pos=col - len(PROMPT))
                return [(m, m) for m in matches]
