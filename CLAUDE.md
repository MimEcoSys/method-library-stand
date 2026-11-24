# method-library-stand - instructions for Claude Code

> **Class:** DS/instrument. Data domains and writer/owner/readers are in `README.md`.

## Work-Product Gate

Non-trivial work (>15 min) here needs an agreed work product, as everywhere in IWE (`~/IWE/CLAUDE.md` §2). Current: WP-581 / WP-608.

## Rules

- Code, prompts and README are in English; scenario replicas may be Russian (concept part 7, question 19).
- Never commit API keys or tokens. Scenarios use invented stories only, no real people's data.
- The stand must not leak project instructions into the tested object: every `claude` process runs in a fresh temporary directory outside this repository (`run_scenario.py`).
- Each run is recorded in the run log, concept part 11 (`aisystant/DS-ecosystem-development`).
