# Stay at the PC until the turn finishes

| Agent activity | Animation |
| --- | --- |
| Thinking after a prompt | Remains awake in its own chair |
| Composing a response after tool work | Remains at the PC; no typing |
| Giving the final response | Returns to its own chair |
| Running tools or scripts locally or remotely | Walks to the PC and types |
| Tools finish; thinking resumes | Remains at the PC without typing |
| Waiting for approval | Raises a hand wherever it is; keeps its PC place after tool work |

The first tool action reserves the agent's PC place through thinking and approval pauses. Idle, stopped, offline and usage-limited agents release their place. Keyboard sounds and typing animation still follow active tool work only. Overlapping Codex tools keep the agent working until the last tool finishes.

**Validation:** State transitions checked across repeated tool/thinking cycles, approval pauses, a fresh prompt, completion, offline and usage-limit states. JavaScript syntax and frame-budget checks passed. Browser animation has not been visually verified.

Reload the room to apply this animation change.
