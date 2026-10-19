# First-user session (19 Oct 2026)

The author installs and learns cogito-mem as a newcomer would. Every question goes here, with the answer and
what the docs must do about it. The user guide and the GitHub Pages site are built from this list.

## Questions

| # | Question, in the user's words | Short answer | What the docs must do |
|---|---|---|---|
| 1 | "The best recommended usage is via Claude hooks?" | Half of it. Hooks *collect* (each turn is saved after Claude answers); the MCP tools let Claude *find* (`memory_query`) and *keep* (`memory_append`). The plugin installs both in one step. | Lead with the plugin. Explain the two halves with Cogi: hooks gather the nuts, MCP is how Claude asks Cogi to fetch one. |

## Findings (friction seen on the way)

| # | What happened | Fix |
|---|---|---|
| F1 | Opening this repository in Claude Code shows a failing MCP server `cogito-mem` (`Connection closed`). The plugin's `.mcp.json` sits at the repo root, so Claude Code also reads it as the *project's* MCP config, where `${CLAUDE_PLUGIN_ROOT}` is empty and the command points at `/scripts/cogito-mem-plugin`. | Move the server into `.claude-plugin/plugin.json` (`mcpServers`), so only the plugin uses it. |
