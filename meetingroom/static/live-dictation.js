// LocalAgreement-2: confirm only a prefix reproduced by two successive decodes.
// The final word remains tentative because the microphone may have caught half of it.
export class TranscriptAgreement {
  constructor() { this.previous = []; this.confirmed = []; }
  update(text) {
    const words = text.trim().split(/\s+/).filter(Boolean);
    const key = w => w.toLocaleLowerCase().replace(/[^\p{L}\p{N}]/gu, "");
    let same = 0;
    while (same < Math.min(words.length, this.previous.length) && key(words[same]) === key(this.previous[same])) same++;
    const consistent = this.confirmed.every((w, i) => words[i] && key(w) === key(words[i]));
    if (consistent) {
      const count = Math.max(this.confirmed.length, Math.min(same, words.length - 1));
      this.confirmed = words.slice(0, count);
    }
    this.previous = words;
    return { confirmed: this.confirmed.join(" "), tentative: consistent ? words.slice(this.confirmed.length).join(" ") : "" };
  }
}
