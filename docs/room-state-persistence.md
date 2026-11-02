# Room state survives leaving and returning

Implemented in the room animation. Reload an open room once to activate it.

| Saved for each room in this browser | Restored when you return |
| --- | --- |
| Agent locations and facing direction | Continue from the previous positions |
| Sitting, leaning and walking state | Keep the previous pose while live activity updates |
| Computer seat and nearby standing spots | Keep agents at their assigned computer positions |
| Inactivity and dozing | Preserve the previous rest state |
| Music on/off and sequence position | Resume the music if it was enabled |

The server's current agent activity still takes priority, so agents can move naturally if a task finished while you were away.

Music may require the first click or keypress after returning because of browser autoplay rules. Audio stops while you are outside the room.

Snapshots save every second, when the page becomes hidden, and when you leave. Separate rooms retain separate snapshots. This is local to the browser.

## Verification

Passed automated checks for snapshot round trips, room separation, agent position and pose restoration, computer occupancy, malformed or unavailable storage, music resume after autoplay blocking, and avoiding duplicate music schedulers. The existing 30 FPS scheduling checks also pass at 60, 120 and 144 Hz. Full browser rendering has not been manually verified.
