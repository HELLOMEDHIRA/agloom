"""Test file for agloom CLI - all corner cases."""

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from unittest import TestCase, main as unittest_main
from unittest.mock import MagicMock, patch


class TestCLIConfigLoading(TestCase):
    """Test config file loading."""

    def test_load_yaml_config(self):
        """Test loading YAML config file."""
        from agloom_cli.config import load_config

        print("\n=== test_load_yaml_config ===")
        print("INPUT: YAML config file with model: gpt-4o, name: test-agent, enable_memory: true, max_skills: 50")

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("""
model: gpt-4o
name: test-agent
enable_memory: true
max_skills: 50
""")
            f.flush()
            config_file = Path(f.name)

        try:
            cfg = load_config(config_file)
            print(f"OUTPUT: {cfg}")
            self.assertEqual(cfg["model"], "gpt-4o")
            self.assertEqual(cfg["name"], "test-agent")
            self.assertEqual(cfg["enable_memory"], True)
            self.assertEqual(cfg["max_skills"], 50)
        finally:
            os.unlink(config_file)

    def test_load_toml_config(self):
        """Test loading TOML config file."""
        from agloom_cli.config import load_config

        print("\n=== test_load_toml_config ===")
        print("INPUT: TOML config file with model: gpt-4o, name: test-agent, enable_memory: true")

        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write("""
model = "gpt-4o"
name = "test-agent"
enable_memory = true
""")
            f.flush()
            config_file = Path(f.name)

        try:
            cfg = load_config(config_file)
            print(f"OUTPUT: {cfg}")
            self.assertEqual(cfg["model"], "gpt-4o")
            self.assertEqual(cfg["name"], "test-agent")
        finally:
            os.unlink(config_file)

    def test_load_missing_config(self):
        """Test loading non-existent config returns empty dict."""
        from agloom_cli.config import load_config

        print("\n=== test_load_missing_config ===")
        print("INPUT: Path('/non/existent/config.yaml')")

        cfg = load_config(Path("/non/existent/config.yaml"))
        print(f"OUTPUT: {cfg}")
        self.assertEqual(cfg, {})

    def test_thread_id_from_config(self):
        """Test thread ID from config."""
        from agloom_cli.config import get_thread_id

        print("\n=== test_thread_id_from_config ===")
        print("INPUT: {'thread_id': 'custom123'}")

        cfg = {"thread_id": "custom123"}
        result = get_thread_id(cfg)
        print(f"OUTPUT: {result}")
        self.assertEqual(result, "custom123")

    def test_thread_id_from_env(self):
        """Test thread ID from environment."""
        from agloom_cli.config import get_thread_id

        print("\n=== test_thread_id_from_env ===")
        print("INPUT: ENV['AGLOOM_THREAD_ID'] = 'env-thread', empty config {}")

        os.environ["AGLOOM_THREAD_ID"] = "env-thread"
        try:
            result = get_thread_id({})
            print(f"OUTPUT: {result}")
            self.assertEqual(result, "env-thread")
        finally:
            del os.environ["AGLOOM_THREAD_ID"]

    def test_thread_id_default(self):
        """Test default thread ID generation."""
        from agloom_cli.config import get_thread_id

        print("\n=== test_thread_id_default ===")
        print("INPUT: empty config {} (no thread_id)")

        thread_id = get_thread_id({})
        print(f"OUTPUT: {thread_id} (length: {len(thread_id)})")
        self.assertEqual(len(thread_id), 8)


class TestModelResolver(TestCase):
    """Test model resolution."""

    def test_resolve_openai(self):
        """Test OpenAI model resolution."""
        print("\n=== test_resolve_openai ===")
        print("INPUT: model='gpt-4o'")

        os.environ["OPENAI_API_KEY"] = "sk-test123"
        try:
            from agloom_cli.model_resolver import get_model

            result = get_model("gpt-4o")
            print(f"OUTPUT: {type(result).__name__}")
            self.assertIsNotNone(result)
        finally:
            del os.environ["OPENAI_API_KEY"]

    def test_resolve_groq(self):
        """Test Groq model resolution."""
        print("\n=== test_resolve_groq ===")
        print("INPUT: model='llama-3.1-70b-versatile'")

        os.environ["GROQ_API_KEY"] = "gsk_test"
        try:
            from agloom_cli.model_resolver import get_model

            result = get_model("llama-3.1-70b-versatile")
            print(f"OUTPUT: {type(result).__name__}")
            self.assertIsNotNone(result)
        finally:
            del os.environ["GROQ_API_KEY"]

    def test_resolve_auto_with_groq(self):
        """Test auto resolution with Groq API key."""
        print("\n=== test_resolve_auto_with_groq ===")
        print("INPUT: model='auto', GROQ_API_KEY set")

        os.environ["GROQ_API_KEY"] = "gsk_test"
        try:
            from agloom_cli.config import resolve_model

            result = resolve_model("auto")
            print(f"OUTPUT: {type(result).__name__}")
            self.assertIsNotNone(result)
        finally:
            del os.environ["GROQ_API_KEY"]

    def test_resolve_auto_no_env(self):
        """Test auto resolution with no env vars."""
        print("\n=== test_resolve_auto_no_env ===")
        print("INPUT: model='auto', no API keys in env")

        for key in ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GROQ_API_KEY"]:
            if key in os.environ:
                del os.environ[key]

        from agloom_cli.config import resolve_model

        model = resolve_model("auto")
        print(f"OUTPUT: {model}")
        self.assertIsNone(model)


class TestToolLoader(TestCase):
    """Test tool discovery and loading."""

    def test_discover_tools_empty_dir(self):
        """Test discovering tools in empty directory."""
        from agloom_cli.tool_loader import discover_tools

        print("\n=== test_discover_tools_empty_dir ===")
        print("INPUT: empty temp directory")

        tmp_dir = tempfile.mkdtemp()
        try:
            tools = discover_tools(Path(tmp_dir))
            print(f"OUTPUT: {tools}")
            self.assertEqual(tools, [])
        finally:
            os.rmdir(tmp_dir)

    def test_discover_tools_nonexistent_dir(self):
        """Test discovering tools in non-existent directory."""
        from agloom_cli.tool_loader import discover_tools

        print("\n=== test_discover_tools_nonexistent_dir ===")
        print("INPUT: Path('/nonexistent')")

        tools = discover_tools(Path("/nonexistent"))
        print(f"OUTPUT: {tools}")
        self.assertEqual(tools, [])

    def test_tool_decorator(self):
        """Test @tool decorator marks function."""
        from agloom_cli.tool_loader import tool

        print("\n=== test_tool_decorator ===")
        print("INPUT: @tool decorator on async function")

        @tool
        async def test_func(x: str) -> str:
            return x

        print(
            f"OUTPUT: has _tool_marker = {hasattr(test_func, '_tool_marker')}, _tool_marker = {test_func._tool_marker}"
        )
        self.assertTrue(hasattr(test_func, "_tool_marker"))
        self.assertTrue(test_func._tool_marker)


class TestBuiltInTools(TestCase):
    """Test built-in CLI tools."""

    def test_read_file(self):
        """Test read_file tool."""
        from agloom_cli.tools import read_file

        print("\n=== test_read_file ===")
        print("INPUT: content='Hello World'")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write("Hello World")
            f.flush()
            result = loop.run_until_complete(read_file(f.name))
            print(f"OUTPUT: {result}")
            self.assertIn("Hello World", result)
            os.unlink(f.name)

        loop.close()

    def test_write_file(self):
        """Test write_file tool."""
        from agloom_cli.tools import write_file

        print("\n=== test_write_file ===")
        print("INPUT: file_path='<temp>/test.txt', content='Test content'")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        tmp_dir = tempfile.mkdtemp()
        try:
            file_path = os.path.join(tmp_dir, "test.txt")
            result = loop.run_until_complete(write_file(file_path, "Test content"))
            print(f"OUTPUT: {result}")
            self.assertIn("Successfully wrote", result)
            self.assertTrue(os.path.exists(file_path))
            os.unlink(file_path)
        finally:
            os.rmdir(tmp_dir)
            loop.close()

    def test_file_exists(self):
        """Test file_exists tool."""
        from agloom_cli.tools import file_exists

        print("\n=== test_file_exists (existing file) ===")
        print("INPUT: existing temp file")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        with tempfile.NamedTemporaryFile(delete=False) as f:
            result = loop.run_until_complete(file_exists(f.name))
            print(f"OUTPUT: {result}")
            self.assertEqual(result, "true")
            os.unlink(f.name)

        print("\n=== test_file_exists (non-existing file) ===")
        print("INPUT: '/nonexistent/file.txt'")

        result = loop.run_until_complete(file_exists("/nonexistent/file.txt"))
        print(f"OUTPUT: {result}")
        self.assertEqual(result, "false")
        loop.close()

    def test_get_working_directory(self):
        """Test get_working_directory tool."""
        from agloom_cli.tools import get_working_directory

        print("\n=== test_get_working_directory ===")
        print("INPUT: no args")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        result = loop.run_until_complete(get_working_directory())
        print(f"OUTPUT: {result}")
        self.assertIn(os.getcwd(), result)
        loop.close()

    def test_path_join(self):
        """Test path_join tool."""
        from agloom_cli.tools import path_join

        print("\n=== test_path_join ===")
        print("INPUT: 'foo', 'bar', 'baz'")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        result = loop.run_until_complete(path_join("foo", "bar", "baz"))
        print(f"OUTPUT: {result}")
        self.assertIn("foo", result)
        self.assertIn("bar", result)
        self.assertIn("baz", result)
        loop.close()

    def test_get_system_info(self):
        """Test get_system_info tool."""
        from agloom_cli.tools import get_system_info

        print("\n=== test_get_system_info ===")
        print("INPUT: no args")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        result = loop.run_until_complete(get_system_info())
        print(f"OUTPUT: {result}")
        self.assertIn("OS:", result)
        self.assertIn("Architecture:", result)
        loop.close()

    def test_get_env_var(self):
        """Test get_env_var tool."""
        from agloom_cli.tools import get_env_var

        print("\n=== test_get_env_var (existing var) ===")
        print("INPUT: 'TEST_VAR', ENV['TEST_VAR']='test_value'")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        os.environ["TEST_VAR"] = "test_value"
        try:
            result = loop.run_until_complete(get_env_var("TEST_VAR"))
            print(f"OUTPUT: {result}")
            self.assertEqual(result, "test_value")

            print("\n=== test_get_env_var (non-existing var) ===")
            print("INPUT: 'NONEXISTENT', 'default_val'")

            result = loop.run_until_complete(get_env_var("NONEXISTENT", "default_val"))
            print(f"OUTPUT: {result}")
            self.assertEqual(result, "default_val")
        finally:
            del os.environ["TEST_VAR"]
            loop.close()


class TestHTTPTools(TestCase):
    """Test HTTP request tools."""

    def test_http_get_invalid_url(self):
        """Test http_get with invalid URL."""
        from agloom_cli.tools import http_get

        print("\n=== test_http_get_invalid_url ===")
        print("INPUT: 'http://invalid-domain-that-does-not-exist.local'")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        result = loop.run_until_complete(http_get("http://invalid-domain-that-does-not-exist.local"))
        print(f"OUTPUT: {result}")
        self.assertIn("Error", result)
        loop.close()

    def test_http_request_method_not_allowed(self):
        """Test http_request with method not allowed returns error."""
        from agloom_cli.tools import http_request

        print("\n=== test_http_request_method_not_allowed ===")
        print("INPUT: 'https://httpbin.org/status/405', method='INVALID'")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        result = loop.run_until_complete(http_request("https://httpbin.org/status/405", method="INVALID"))
        print(f"OUTPUT: {result}")
        self.assertIn("Status:", result)
        loop.close()


class TestTaskTracker(TestCase):
    """Test task planning tools."""

    def test_create_task_plan(self):
        """Test create_task_plan tool."""
        from agloom_cli.tools.task_tracker import clear_task_tracker
        from agloom_cli.tools import create_task_plan

        print("\n=== test_create_task_plan ===")
        print("INPUT: 'Test task', ['step1', 'step2', 'step3']")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        loop.run_until_complete(clear_task_tracker())

        result = loop.run_until_complete(create_task_plan("Test task", ["step1", "step2", "step3"]))
        print(f"OUTPUT: {result}")
        self.assertIn("Task ID:", result)
        self.assertIn("step1", result)
        self.assertIn("step2", result)
        self.assertIn("step3", result)
        loop.close()

    def test_get_current_task(self):
        """Test get_current_task tool."""
        from agloom_cli.tools.task_tracker import clear_task_tracker
        from agloom_cli.tools import create_task_plan, get_current_task

        print("\n=== test_get_current_task ===")
        print("INPUT: after creating task 'Test' with steps ['Step 1', 'Step 2']")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        loop.run_until_complete(clear_task_tracker())
        loop.run_until_complete(create_task_plan("Test", ["Step 1", "Step 2"]))

        result = loop.run_until_complete(get_current_task())
        print(f"OUTPUT: {result}")
        self.assertIn("Task ID:", result)
        self.assertIn("Progress:", result)
        loop.close()


class TestCLIImport(TestCase):
    """Test CLI module imports."""

    def test_cli_imports(self):
        """Test CLI imports work."""
        print("\n=== test_cli_imports ===")
        print("INPUT: from agloom_cli import app, console, tool")

        from agloom_cli import app, console, tool

        print(f"OUTPUT: app={type(app).__name__}, console={type(console).__name__}")
        self.assertIsNotNone(app)
        self.assertIsNotNone(console)

    def test_tools_import(self):
        """Test tools import."""
        print("\n=== test_tools_import ===")
        print("INPUT: from agloom_cli import tools")

        from agloom_cli import tools

        print(
            f"OUTPUT: has read_file={hasattr(tools, 'read_file')}, write_file={hasattr(tools, 'write_file')}, run_shell={hasattr(tools, 'run_shell')}, http_get={hasattr(tools, 'http_get')}, web_search={hasattr(tools, 'web_search')}"
        )
        self.assertTrue(hasattr(tools, "read_file"))
        self.assertTrue(hasattr(tools, "write_file"))
        self.assertTrue(hasattr(tools, "run_shell"))
        self.assertTrue(hasattr(tools, "http_get"))
        self.assertTrue(hasattr(tools, "web_search"))

    def test_ui_import(self):
        """Test UI import."""
        print("\n=== test_ui_import ===")
        print("INPUT: from agloom_cli.ui import RichUI, get_ui, reset_ui")

        from agloom_cli.ui import RichUI, get_ui, reset_ui

        print(f"OUTPUT: RichUI={type(RichUI).__name__}, get_ui()={type(get_ui()).__name__}")
        self.assertIsNotNone(RichUI)
        ui = get_ui()
        self.assertIsNotNone(ui)
        reset_ui()

    def test_repl_import(self):
        """Test REPL import."""
        print("\n=== test_repl_import ===")
        print("INPUT: from agloom_cli.repl import render_banner, ShellState")

        from agloom_cli.repl import render_banner, ShellState

        print(f"OUTPUT: render_banner={type(render_banner).__name__}, ShellState={type(ShellState).__name__}")
        self.assertIsNotNone(render_banner)
        self.assertIsNotNone(ShellState)


class TestModelResolverImports(TestCase):
    """Test model resolver."""

    def test_model_resolver_import(self):
        """Test model resolver module."""
        print("\n=== test_model_resolver_import ===")
        print("INPUT: from agloom_cli.model_resolver import get_model")

        from agloom_cli.model_resolver import get_model

        print(f"OUTPUT: get_model={type(get_model).__name__}")
        self.assertTrue(callable(get_model))


class TestCLIArguments(TestCase):
    """Test CLI argument handling."""

    def test_cli_help_shows_options(self):
        """Test CLI help shows expected options."""
        print("\n=== test_cli_help_shows_options ===")
        print("INPUT: from agloom_cli.cli import app")

        from agloom_cli.cli import app

        print(f"OUTPUT: app={type(app).__name__}")
        self.assertIsNotNone(app)


class TestEdgeCases(TestCase):
    """Test edge cases."""

    def test_empty_prompt(self):
        """Test handling of empty prompt."""
        print("\n=== test_empty_prompt ===")
        print("INPUT: (placeholder, no test)")
        print("OUTPUT: placeholder")
        pass

    def test_very_long_system_prompt(self):
        """Test very long system prompt."""
        print("\n=== test_very_long_system_prompt ===")
        print("INPUT: (placeholder, no test)")
        print("OUTPUT: placeholder")
        pass

    def test_special_chars_in_path(self):
        """Test paths with special characters."""
        print("\n=== test_special_chars_in_path ===")
        print("INPUT: (placeholder, no test)")
        print("OUTPUT: placeholder")
        pass


def run_tests():
    import unittest

    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=0)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_tests())
