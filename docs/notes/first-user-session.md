# First-user session (19 Oct 2026)

The author installs and learns cogito-mem as a newcomer would. Every question goes here, with the answer and
what the docs must do about it. The user guide and the GitHub Pages site are built from this list.

## Questions

| # | Question, in the user's words | Short answer | What the docs must do |
|---|---|---|---|
| 1 | "The best recommended usage is via Claude hooks?" | Half of it. Hooks *collect* (each turn is saved after Claude answers); the MCP tools let Claude *find* (`memory_query`) and *keep* (`memory_append`). The plugin installs both in one step. | Lead with the plugin. Explain the two halves with Cogi: hooks gather the nuts, MCP is how Claude asks Cogi to fetch one. |
| 2 | (How the user pictures it) "Each message and answer will be remembered. When the session gets really long, I can ask about something that is no longer in the context window, and Claude uses cogito-mem to recall it." | Yes, that is the main use case. Every typed message and every reply is saved after each turn. Claude searches when you refer back to something; saying "check your memory" makes sure it does. | Use these words on the home page: it is the clearest picture of what the tool does. Show the long-session case (this very session compacted from 782k to 13k tokens). |
| 3 | "Could you explain how the service works?" | Cogi collects every message after each answer, keeps it word for word with its date, and finds it again by words and by meaning. Claude asks, Cogi brings back the best few. All on your computer. | A "How it works" page: the 3 steps (collect, store, find) with Cogi and one picture; details (files, model, search) below the fold. |
| 4 | "How does the API look?" | Two operations, `append` and `query`, on one endpoint (`POST /v1/memory`), with the same JSON from HTTP, Python, the CLI and the two MCP tools. | An API & MCP page: the two calls with a real request and a real (trimmed) reply first; every optional key in a table below; MCP tools and how to connect any client. |

## Findings (friction seen on the way)

| # | What happened | Fix |
|---|---|---|
| F1 | Opening this repository in Claude Code shows a failing MCP server `cogito-mem` (`Connection closed`). The plugin's `.mcp.json` sits at the repo root, so Claude Code also reads it as the *project's* MCP config, where `${CLAUDE_PLUGIN_ROOT}` is empty and the command points at `/scripts/cogito-mem-plugin`. | Move the server into `.claude-plugin/plugin.json` (`mcpServers`), so only the plugin uses it. |
| F2 | Claude Code saves its compaction summary as a `user` message (`isCompactSummary: true`); capture would store it as if the user had typed it. | Skip `isCompactSummary` records in `capture/claude_code.py` (later; not fixed during the session). |
