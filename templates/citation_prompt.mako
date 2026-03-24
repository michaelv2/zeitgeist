You are given the following markdown memo generated from various sources like prediction markets, news, FRED data points, catalysts etc:

```md
${memo}
```

Your goal is to add citations to the memo by hyperlinking SHORT existing phrases to relevant source URLs.

## Rules

1. **Hyperlink existing words only** — pick 1-2 words already in the text and wrap them: `[existing words](url)`
2. **NEVER insert the article title, site name, or any new text** — the only characters you may add are `[`, `](url)`, and nothing else
3. **Keep links short** — 1-2 words max inside the brackets. Never link a full clause or sentence.
4. **One link per source per paragraph** — do not cluster multiple citation links back-to-back. Spread them naturally across the text.
5. **Preserve all original text exactly** — no additions, deletions, or rewordings beyond the markdown link syntax

## Example

BEFORE: Senate close to DHS funding deal; ICE remains sticking point, causing major airport disruptions with 6+ hour TSA waits.
AFTER:  Senate close to [DHS funding](url1) deal; ICE remains sticking point, causing major airport disruptions with 6+ hour [TSA waits](url2).

Notice: only existing words are linked, links are 1-2 words each, and the original text is otherwise identical.

Return JUST the markdown with citations added. No backticks, no commentary.
