"""Built-in CLI tools — filesystem, shell, web, http, tasks.

These tools provide cross-platform support for CLI operations.
"""

from .filesystem import (
    read_file,
    write_file,
    list_directory,
    file_exists,
    create_directory,
    remove_file,
    copy_file,
    move_file,
    get_file_info,
    search_files,
)
from .http import (
    http_request,
    http_get,
    http_post,
    http_put,
    http_delete,
    http_head,
    fetch_json,
)
from .shell import (
    run_shell,
    run_shell_interactive,
    get_system_info,
    get_env_var,
    set_env_var,
    list_env_vars,
)
from .task_tracker import (
    create_task_plan,
    get_current_task,
    complete_step,
    update_task_progress,
    show_remaining_steps,
    clear_task_tracker,
)
from .web_search import (
    web_search,
    search_web,
    find_docs,
    search_github,
)
from .working_dir import (
    get_working_directory,
    set_working_directory,
    push_working_directory,
    pop_working_directory,
    path_join,
    path_parent,
    path_absolute,
    path_exists,
    path_is_file,
    path_is_directory,
    path_basename,
    path_extension,
    path_stem,
)

__all__ = [
    # Filesystem
    "read_file",
    "write_file",
    "list_directory",
    "file_exists",
    "create_directory",
    "remove_file",
    "copy_file",
    "move_file",
    "get_file_info",
    "search_files",
    # HTTP
    "http_request",
    "http_get",
    "http_post",
    "http_put",
    "http_delete",
    "http_head",
    "fetch_json",
    # Shell
    "run_shell",
    "run_shell_interactive",
    "get_system_info",
    "get_env_var",
    "set_env_var",
    "list_env_vars",
    # Task tracking
    "create_task_plan",
    "get_current_task",
    "complete_step",
    "update_task_progress",
    "show_remaining_steps",
    "clear_task_tracker",
    # Web search
    "web_search",
    "search_web",
    "find_docs",
    "search_github",
    # Working directory
    "get_working_directory",
    "set_working_directory",
    "push_working_directory",
    "pop_working_directory",
    "path_join",
    "path_parent",
    "path_absolute",
    "path_exists",
    "path_is_file",
    "path_is_directory",
    "path_basename",
    "path_extension",
    "path_stem",
]
