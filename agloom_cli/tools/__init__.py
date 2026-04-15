"""Built-in CLI tools — filesystem, shell, web, http, tasks.

These tools provide cross-platform support for CLI operations.
"""

from .filesystem import (
    copy_file,
    create_directory,
    file_exists,
    get_file_info,
    list_directory,
    move_file,
    read_file,
    remove_file,
    search_files,
    write_file,
)
from .http import (
    fetch_json,
    http_delete,
    http_get,
    http_head,
    http_post,
    http_put,
    http_request,
)
from .shell import (
    get_env_var,
    get_system_info,
    list_env_vars,
    run_shell,
    run_shell_interactive,
    set_env_var,
)
from .task_tracker import (
    clear_task_tracker,
    complete_step,
    create_task_plan,
    get_current_task,
    show_remaining_steps,
    update_task_progress,
)
from .web_search import (
    find_docs,
    search_github,
    search_web,
    web_search,
)
from .working_dir import (
    get_working_directory,
    path_absolute,
    path_basename,
    path_exists,
    path_extension,
    path_is_directory,
    path_is_file,
    path_join,
    path_parent,
    path_stem,
    pop_working_directory,
    push_working_directory,
    set_working_directory,
)

__all__ = [
    "clear_task_tracker",
    "complete_step",
    "copy_file",
    "create_directory",
    # Task tracking
    "create_task_plan",
    "fetch_json",
    "file_exists",
    "find_docs",
    "get_current_task",
    "get_env_var",
    "get_file_info",
    "get_system_info",
    # Working directory
    "get_working_directory",
    "http_delete",
    "http_get",
    "http_head",
    "http_post",
    "http_put",
    # HTTP
    "http_request",
    "list_directory",
    "list_env_vars",
    "move_file",
    "path_absolute",
    "path_basename",
    "path_exists",
    "path_extension",
    "path_is_directory",
    "path_is_file",
    "path_join",
    "path_parent",
    "path_stem",
    "pop_working_directory",
    "push_working_directory",
    # Filesystem
    "read_file",
    "remove_file",
    # Shell
    "run_shell",
    "run_shell_interactive",
    "search_files",
    "search_github",
    "search_web",
    "set_env_var",
    "set_working_directory",
    "show_remaining_steps",
    "update_task_progress",
    # Web search
    "web_search",
    "write_file",
]
