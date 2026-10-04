// Conventional Commits grammar for this project.
// Pair with husky's commit-msg hook locally and a PR-title check in CI.
// Edit `scope-enum` to match your project's areas (see CLAUDE.md → Configuration).
module.exports = {
  extends: ['@commitlint/config-conventional'],
  rules: {
    // <type>(<area>): subject
    'type-enum': [
      2,
      'always',
      ['feat', 'fix', 'docs', 'chore', 'test', 'style', 'refactor', 'perf', 'ci'],
    ],
    // Areas - keep in sync with the `area:` labels and branch scopes.
    // Compound scopes (e.g. mobile-backend) are allowed for cross-area work.
    'scope-enum': [
      2,
      'always',
      [
        'backend',
        'frontend',
        'ingest',
        'ai',
        'devops',
        'docs',
        'repo',
      ],
    ],
    'scope-empty': [2, 'never'], // always require an area scope
    'subject-case': [0], // allow any subject casing
    'header-max-length': [2, 'always', 100],
  },
}
