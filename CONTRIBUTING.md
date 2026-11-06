# Contributing to IS MU MCP Server

Thank you for your interest in improving the IS MU MCP server.

## Issues and Bug Reports

If you encounter any problems, bugs, or have ideas for new features:
1. Check existing [GitHub Issues](https://github.com/davidskrecek/mcp-is-muni/issues) to avoid duplicates.
2. Open a new issue using the provided **Bug Report** or **Feature Request** templates.
3. **Important**: Never paste sensitive session cookies (`__Host-issession`, `__Host-iscreds`), passwords, or personal identity numbers into issues or comments.

## Pull Requests

Direct pushes to the `main` branch are restricted:
1. **Fork** the repository and create your feature branch:
   ```bash
   git checkout -b feature/your-feature-name
   ```
2. Implement your changes following standard code quality and formatting guidelines.
3. Ensure the FastMCP server runs without syntax errors:
   ```bash
   uv run mcp-is-muni
   ```
4. Push to your fork and submit a **Pull Request** targeting the `main` branch.
5. All pull requests require explicit review and approval by the maintainer before they can be merged.
