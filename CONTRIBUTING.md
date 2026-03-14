# Contributing to Zapros

## Development Setup

Install dependencies using uv:

```bash
uv sync --all-extras
```

Run linters and tests:

```bash
scripts/lint
scripts/test
```

## Release Process

Zapros uses [release-please](https://github.com/googleapis/release-please) for automated releases.

### How It Works

1. When commits are pushed to `main`, release-please automatically creates or updates a release PR
2. The release PR includes:
   - Updated version in `pyproject.toml`
   - Generated `CHANGELOG.md` from conventional commits
3. When the release PR is merged, release-please:
   - Creates a GitHub release
   - Triggers automatic publishing to PyPI
   - Uploads build artifacts to the GitHub release

### Commit Convention

Use [Conventional Commits](https://www.conventionalcommits.org/) to ensure proper changelog generation:

- `feat:` - New features (bumps minor version)
- `fix:` - Bug fixes (bumps patch version)
- `chore:` - Maintenance tasks
- `docs:` - Documentation changes
- `refactor:` - Code refactoring
- `test:` - Test updates

Breaking changes: Add `!` after type (e.g., `feat!:`) or include `BREAKING CHANGE:` in commit body to bump major version.

### Manual Release

To trigger a release:
1. Merge the release-please PR when ready
2. The publish workflow automatically runs when the release is created

You can also manually trigger the publish workflow from the Actions tab.

## Documentation

Documentation is built with VitePress.

### Local Development

```bash
npm run docs:dev
```

### Build Documentation

```bash
npm run docs:build
```

### Preview Production Build

```bash
npm run docs:preview
```
