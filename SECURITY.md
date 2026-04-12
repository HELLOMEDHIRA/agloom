# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 0.1.x   | Yes                |

## Reporting a Vulnerability

If you discover a security vulnerability in agloom, please report it responsibly.

**Do NOT open a public GitHub issue for security vulnerabilities.**

Instead, please use one of these methods:

1. **GitHub Security Advisory** (preferred): Go to the [Security tab](https://github.com/HELLOMEDHIRA/agloom/security/advisories/new) and create a private advisory.

2. **Email**: Send details to [hello.medhira@gmail.com](mailto:hello.medhira@gmail.com).

### What to Include

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if you have one)

### Response Timeline

- **Acknowledgment**: Within 48 hours
- **Initial assessment**: Within 1 week
- **Fix or mitigation**: Best effort within 2 weeks for critical issues

### After Resolution

Once the vulnerability is fixed and a new version is released, we will:

1. Credit the reporter (unless they prefer anonymity)
2. Publish a security advisory on GitHub
3. Update the CHANGELOG with the fix

## Security Best Practices for Users

- Never commit API keys or secrets to your repository
- Use environment variables for `GROQ_API_KEY` and other credentials
- Review tool definitions before granting agents access to sensitive operations
- Use `interrupt_before_tools` for tools that modify external systems
- Set appropriate `llm_timeout` and `rate_limit` values for production
