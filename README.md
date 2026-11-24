# method-library-stand

**Class:** DS/instrument
**Purpose:** a test stand that checks how an AI assistant connected to the Aisystant Method Library MCP (`https://lib.aisystant.ai/mcp`) offers and leads a person through a method.
**Created:** 2026-11-24 via `/repo-new`

The stand runs a conversation between three parties and stores the record:

1. **Tester** - an AI agent with a scenario (first message, facts of its story, ready answer to a method offer). It plays the person.
2. **Tested object** - Claude Code connected only to the library MCP (`search`, `read`).
3. **Evaluator** - an AI agent that reads the full record, including MCP calls, and gives a verdict per criterion.

Concept, test method and run log (in Russian): `aisystant/DS-ecosystem-development`, folder `0.OPS/0.9.Inbox/WP-581-concept-open-mcp-method-library` (parts 6, 10, 11).

## Run

Requires the `claude` CLI signed in on the machine that runs the stand.

```sh
python3 run_scenario.py <scenario_id> [run_tag]
```

Scenarios are in `scenarios.json`, prompts in `prompts/`. Each run writes `runs/<YYYY-MM-DD>/<scenario_id>-<run_tag>.json`. Every `claude` process starts in a fresh empty temporary directory, so no project instructions reach the three parties. `runs/2026-11-22-trial/` holds the first trial run (one run per scenario).

## Data domains

| Data | Home | Sensitivity | Quarantine |
|-----|-----|-------------------|----------|
| Stand code, prompts, scenarios | this repository | team-internal | none |
| Run records (conversations of the Tester with the tested object) | `runs/` | team-internal; scenarios are invented stories, no real people | none |

**Outside-axis quarantine (secrets, payment data, other people's PII):** never commit API keys or tokens; keys live only in the runner's environment or repository secrets. Scenarios and run records contain no real people's data.

## Writer / Owner / Readers

- **Writer:** Tseren with an AI agent (Claude Code)
- **Owner:** Tseren
- **Readers:** the MIM / Aisystant IT team (Andrey, Hermes)

## Gate receipt (projection)

```yaml
approved_by: pilot
approved_at: 2026-11-24
approval_scope: instance
wp_ref: WP-581
```
