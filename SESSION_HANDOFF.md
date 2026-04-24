# noah-unified-commerce - Session Context

![Continuity](https://raw.githubusercontent.com/hackerware/continuity/main/assets/icon.png)

## Cross-LLM Resumption
To resume this session in ANY AI tool:
1. Read this file for project context
2. Read `.continuity/SESSION_NOTES.md` for goals/blockers/next steps
3. Read `.continuity/unfinished-task.json` for structured resume state
4. Call `get_quick_context` if MCP is available

## AI Assistant: Engineering Guardrails

**Honesty:** State facts only if certain. Label suggestions with confidence level. Label speculation explicitly.

**Decision Logging:** Log decisions that change structure, behavior, or long-term direction immediately after the change. If you're unsure whether something qualifies, say so explicitly and follow the project instructions.

**MCP Availability:** Client capabilities differ. If Continuity MCP tools are available, use them first. If not, fall back to the repo instruction files and session notes instead of assuming memory is connected.

**Workspace Self-Test:** Check `.continuity/mcp-health.json` or resource `continuity://mcp-health` for the latest workspace-target probe. This is about the workspace MCP target, not proof that the current chat client has mounted Continuity.

**Search First:** Before proposing architectural changes, call `search_decisions(query: "keyword")` to check for prior decisions.

**Recovery:** If you realize earlier decisions were not logged, pause, summarize, log retroactively, and inform the user.

**Transparency:** Inform the user when you log decisions, recover missed decisions, detect drift, or find conflicts with past decisions.

**When MCP is connected, richer guardrails are available via resource `continuity://session-handoff`.**

---

## 🏗️ Architecture Overview

**Core Systems:**
- **Decision Logging** - Smart clipboard detection, 5 templates, auto-tag extraction
- **Documentation Tracking** - AST parsing with TypeScript compiler API, semantic change detection
- **File Protection** - Prevent AI modification of critical files (.env, credentials)
- **MCP Integration** - Works with Claude Code, Codex, Cursor, Copilot, Gemini, Cline/Roo, and other MCP-capable clients
- **Delta Tracking** - Shows what changed since last sync
- **Auto-Sync** - Hands-free workflow automation

**Technical Depth:**
- TypeScript Compiler API (ts.createSourceFile, ts.SyntaxKind) for AST parsing
- Exports: functions, classes, interfaces, types, constants
- Tracks: signatures, async status, parameters, return types, JSDoc
- Change detection: new/removed exports, signature changes, async conversions
- Markdown parsing: code blocks, inline code, file references
- Gitignore pattern matching with glob-to-regex conversion
- Smart .txt filtering (docs/, notes/, guides/ folders only)

**Storage:**
- `.continuity/decisions.json` - Architectural decisions
- `.continuity/doc-status.json` - Documentation status
- `.continuity/doc-exports.json` - Code exports snapshot
- `.continuity/delta-snapshot.json` - Last sync state
- `.continuity/protected-files.json` - Protected file patterns
- `SESSION_HANDOFF.md` - Full context for AI handoff


## Project Purpose
No description available

## Recent Changes
**Branch:** module-4

**Modified:**
- .continuity/convergence.json
- .continuity/current-session.json
- .continuity/delta-snapshot.json
- .continuity/metrics.json
- .continuity/unfinished-task.json
- .continuity/working-memory.json
- SESSION_HANDOFF.md


## Recent Commits
- `864357c` feat: initialize project structure and implement dashboard service (duyvinh09)
- `abbc25f` Finished Module 3(order_api, order_worker, report_service) (Quochuydeptrainhatthegioi1202)
- `7f23e2d` feat: hoàn thành module-2 và xử lý dữ liệu lỗi csv (Ngoc Vu)
- `a09cf38` setup enviroment (NamLe1808)
- `dfe8431` first commit (NamLe1808)


## Project Structure
.continuity/
README.md
SESSION_HANDOFF.md
docker-compose.yml
kong/
mysql/
services/
shared/
swagger/

---

## Session Checklist

- [x] Read SESSION_HANDOFF.md
- [ ] Verify whether Continuity MCP tools are available in this client
- [ ] If MCP is unavailable, use repo instruction files, `.continuity/mcp-health.json`, and `.continuity/unfinished-task.json` as fallback context
- [ ] Search past decisions before proposing architectural changes
- [ ] Log architectural decisions (only structural/behavioral/directional changes)
- [ ] Inform user when decisions are logged, recovered, or conflicts detected
- [ ] Recover any missed decisions before session ends

---
Generated: 2026-04-24T13:59:18.920Z
