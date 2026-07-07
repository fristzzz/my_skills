# my_skills

A personal collection of skills for AI coding agents (Pi, Claude Code, etc.).

Each skill is a self-contained directory with a `SKILL.md` (trigger + routing) plus executable scripts under `scripts/`.

## Layout

```
my_skills/
└── <skill-name>/
    ├── SKILL.md              # required: frontmatter + routing
    ├── scripts/              # optional: callable Python/Bash helpers
    └── evals/                # optional: test cases
```
