# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes       |

## Reporting a Vulnerability

Please **do not** open a public GitHub issue for security vulnerabilities.

1. **GitHub Security Advisory** (preferred): use the [Security advisories](https://github.com/HELLOMEDHIRA/agloom/security/advisories) tab on the repository and open a **private** advisory.
2. **Email**: contact the maintainers at [hello.medhira@gmail.com](mailto:hello.medhira@gmail.com).

Include: description, reproduction steps, impact, and suggested fix if you have one.

## Shell and Tooling Risk

The agloom **CLI** can expose tools that run **shell commands** and access the **filesystem**. Treat deployments like any privileged automation: trust boundaries, secrets handling, and operator approval matter. See the module docstring in `agloom_cli/tools/shell.py` for details on shell invocation.

## Response

We aim to acknowledge reports within a few business days and coordinate disclosure after a fix is available.
