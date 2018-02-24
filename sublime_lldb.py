import os
import sublime
import sublime_plugin

from .sublime_logging import get_logger
from .lldb_rpc_server.process import LldbServerProcess


logger = get_logger(__name__)

LLDB_SERVER_PROCESS = None
PROMPT = '(lldb) '

def load_settings():
    return sublime.load_settings('lldb.sublime-settings')


def plugin_unloaded():
    global LLDB_SERVER_PROCESS

    if LLDB_SERVER_PROCESS is not None:
        LLDB_SERVER_PROCESS.kill()
        LLDB_SERVER_PROCESS = None


def get_lldb_service(window):
    global LLDB_SERVER_PROCESS

    if LLDB_SERVER_PROCESS is None or not LLDB_SERVER_PROCESS.is_running:
        settings = load_settings()

        LLDB_SERVER_PROCESS = LldbServerProcess(
            settings.get('python_binary', 'python'),
            settings.get('lldb_python_lib_directory', None),
        )
    else:
        logger.info('Server already running')

    return window.__dict__.get(
        'lldb-service',
        LLDB_SERVER_PROCESS.connect(),
    )


class LldbRun(sublime_plugin.WindowCommand):

    def run(self, executable_path):
        self.lldb_service = get_lldb_service(self.window)
        if self.lldb_service is not None:
            LLDB_SERVER_PROCESS.set_listener(self)
            self.console = self.window.create_output_panel('lldb')
            self.console.set_name('lldb-console')
            self.console.set_syntax_file('lldb-console.sublime-syntax')
            self.console.settings().set('line_numbers', False)
            self.console.set_scratch(True)
            self.lldb_service.create_target(executable_path)
            target_name = os.path.basename(executable_path)
            self.log('Current executable set to %r' % target_name)
            for file, breakpoints in load_breakpoints(self.window).items():
                for line in breakpoints:
                    br = self.lldb_service.target_set_breakpoint(file, line)
                    self.log(br)
            self.lldb_service.target_launch()

    def on_process_state_changed(self, state):
        if state == 'stopped':
            thread_id = self.lldb_service.process_get_selected_thread()
            line_entry = self.lldb_service.frame_get_line_entry(thread_id, 0)
            self.jump_to(line_entry)

            self.console.run_command('lldb_show_prompt')
        elif state == 'exited':
            self.console.run_command('lldb_hide_prompt')

            for view in self.window.views():
                view.erase_regions('run_pointer')

        self.log('Process %s' % state)

    def log(self, message):
        self.console.run_command('lldb_append_text', {'text': message + '\n'})
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
        self.lldb_service = get_lldb_service(self.window)
        self.lldb_service.process_destroy()


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
        last_line_region = self.view.line(self.view.size())
        line = self.view.substr(last_line_region)
        if line == PROMPT:
            row, col = self.view.rowcol(self.view.size())
            insert_point = self.view.text_point(row - 1, 0)
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
        lldb_service = get_lldb_service(view.window())
        result = lldb_service.handle_command(command)
        if result is not None:
            view.run_command('lldb_append_text', {'text': result})
        else:
            view.run_command('lldb_append_text', {'text': 'Not a valid command\n'})

        view.run_command('lldb_show_prompt')
