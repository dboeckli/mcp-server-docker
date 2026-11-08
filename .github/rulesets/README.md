# Repository rulesets

Versioned copies of the active GitHub rulesets for `main`.

| File | Rules |
|------|-------|
| `main-1.json` | `deletion`, `non_fast_forward` |
| `main-2.json` | `required_linear_history`, `required_status_checks`, `pull_request` |

Adapted from an export of `dboeckli/spring-7-web-services`:

- Branch condition: `refs/heads/master` → `refs/heads/main`
- Required status check: `build` → `Test & lint`, `Integration tests`, `Docker image`
- Merge commits disabled in favor of linear history (squash/rebase only)
- Admin bypass (`RepositoryRole` actor 5) kept so the owner can bypass in emergencies

These files are reference copies. GitHub does not apply them automatically.

## Apply

Create new rulesets (IDs and `source` fields are assigned by the target repository):

```bash
gh api -X POST repos/{owner}/{repo}/rulesets --input .github/rulesets/main-1.json
gh api -X POST repos/{owner}/{repo}/rulesets --input .github/rulesets/main-2.json
```

Update an existing ruleset by ID with `PUT`:

```bash
gh api -X PUT repos/{owner}/{repo}/rulesets/{id} --input .github/rulesets/main-2.json
```
