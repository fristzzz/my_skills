# my_skills

A personal collection of skills for AI coding agents (Pi, Claude Code, etc.).

Each skill is a self-contained directory with a `SKILL.md` (trigger + routing) plus executable scripts under `scripts/`. They can be used as-is or copied into `~/.pi/agent/skills/`, `~/.claude/skills/`, or any agent's skill discovery path.

## Skills

| Skill | What it does |
|---|---|
| [`pdf-acroform/`](./pdf-acroform/) | Create, modify, fill, and operate on PDF forms and documents locally — fill AcroForm fields (with CJK bake-mode fallback for Typst-generated PDFs), change field position / style / font / color, generate fillable PDFs from a JSON layout, batch-fill a template across many records, overlay text/images onto non-editable PDFs (the kind that just has blank lines), merge / split / rotate pages, watermark, encrypt / decrypt, read or set metadata, extract text + images. |

## Layout

```
my_skills/
└── <skill-name>/
    ├── SKILL.md              # required: frontmatter + routing
    ├── scripts/              # optional: callable Python/Bash helpers
    └── evals/                # optional: test cases
```

## License

MIT per skill — see each skill's `SKILL.md` frontmatter.
