# Project Cycle Workflow

```mermaid
flowchart TD
    A[Brief or existing draft] --> B[Planning run]
    B --> C[Reviewed plan version]
    C --> D{Launch ready?}
    D -- No --> E[Edit or retry planning]
    E --> B
    D -- Yes --> F[Launch mission]
    F --> G[Mission runs]
    G --> H{Needs readjustment?}
    H -- No --> I[Complete cycle]
    H -- Yes --> J[Create successor cycle]
    J --> B
```

## Rules

- One cycle maps to one draft lineage.
- A launched mission stays attached to that cycle.
- Readjustment creates a linked successor cycle, not an in-place rewrite.
- Evidence follows the cycle and remains visible after successor creation.
