# Screen marks: point at what's on screen

**How to use it:** press **M** or click **✎ Mark**, then select text or drag a box. A 📌 chip appears; talk (Space) or type, then send.

| What's on screen | How you mark it | What the agent receives | Cost |
|---|---|---|---|
| Code / CSV / text | select text or drag a box | the quoted text and its **line numbers** | a few tokens |
| Markdown | select text | the quoted text and its source line | a few tokens |
| PDF (now shown as pages) | drag a box over a line | the **text under the box** and the page | a few tokens |
| Figure inside a PDF | drag a box | the page, the region and a small crop | ~300–500 tokens, only if opened |
| PNG / JPG plot | drag a box (a click marks a small area) | the region and a crop of at most 640 px | ~300–500 tokens, only if opened |
| HTML page | select text, or drag a box | the selected text, or the text under the box | a few tokens |

- The message goes to **the agent who shared the item** unless you name someone else.
- You can attach several marks to one message. Click a 📌 line in the transcript to see that mark again.
- Agents never get a whole-screen screenshot.
- The app needs a **restart** to pick this up. New dependency: `pypdfium2` (already in `.venv`).
