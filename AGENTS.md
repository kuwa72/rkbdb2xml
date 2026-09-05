# Context Minimization & Tool Usage Rules

- Bash usage policy:
  - Do not use Bash for basic file reading (`cat`, `head`, `less`) or broad searches (`find`, raw recursive `grep`).
  - Use dedicated tools: `read` / `serena_read_file` for files, `glob` / `fd` for discovery.
  - When Bash commands are necessary, always prevent context overflow:
    - Limit output lines using pipes (e.g., `| head -n 30`).
    - If a command generates large logs (tests, builds), redirect output to a temporary file and inspect only errors/summary.
- Code search policy:
  - For structural/symbol exploration (functions, classes, interfaces), prioritize `ast-grep` or Serena LSP tools.
  - For exact string matches, use `rg` with narrow path targeting.
- Architecture understanding:
  - When inspecting multi-file relationships or module structure, use `repomix` with specific glob patterns rather than reading individual files repeatedly.
