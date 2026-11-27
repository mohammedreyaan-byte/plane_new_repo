# Training sandbox and recordings — PLN-027

## Sandbox policy

- Training uses a dedicated sandbox project, never production data.
- The sandbox is reset after each session and after hypercare.
- Test accounts used for training are disabled in production after hypercare and
  the disablement is recorded (`HANDOVER-SANDBOX`).

| Field                      | Value         |
| -------------------------- | ------------- |
| Sandbox project            | Not created   |
| Sandbox owner              | Not named     |
| Reset method               | Not recorded  |
| Reset log                  | None recorded |
| Post-hypercare disablement | Not recorded  |

## Five required short recordings

Record each task on the sandbox and store the link with the evidence register.

|   # | Task                                 | Recording link | Recorded by | Date |
| --: | ------------------------------------ | -------------- | ----------- | ---- |
|   1 | Create and classify a work item      | None recorded  |             |      |
|   2 | Move a bug through its workflow      | None recorded  |             |      |
|   3 | Save and share a filtered view       | None recorded  |             |      |
|   4 | Comment, mention and attach evidence | None recorded  |             |      |
|   5 | Export a report to CSV               | None recorded  |             |      |
