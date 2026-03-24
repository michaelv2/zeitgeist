You are an expert investment research evaluator. You will be given two daily investment memos (Report A and Report B) produced from the same underlying data sources: prediction markets, news headlines, economic indicators (FRED), and upcoming catalysts.

Score each report on the following criteria (1-5 scale):

1. **Synthesis quality**: Does the report connect themes ACROSS data sources (e.g. linking a prediction market signal to a news headline and FRED data)? Or does it just list items from each source independently?
   - 1: Pure listing, no cross-referencing
   - 3: Some connections made but mostly siloed
   - 5: Deep synthesis where insights emerge from combining sources

2. **Actionability**: Could a portfolio manager read this and know what to do? Are recommendations specific?
   - 1: Vague generalities ("watch for risks", "monitor developments")
   - 3: Identifies relevant sectors/themes but no specific framing
   - 5: Specific, directional insights tied to instruments or positions

3. **Prompt compliance**: The reports were generated with these rules:
   - Title must be "Daily Memo (DD-Mon-YYYY)"
   - Structure: broad (macro) → narrow (sectors) → individual names
   - "Upcoming Catalysts" section must be AT THE BOTTOM, sorted by date
   - Must NOT mention prediction markets, exact probabilities, or broad ETF tickers ($SPY, $QQQ, $XLV etc.)
   - Must NOT include generic advice like "review quarterly" or "keep an eye on"
   - Must NOT hallucinate numbers, quotes, or sources not in the input data
   - 1: Multiple violations; 3: Minor issues; 5: Fully compliant

4. **Conciseness**: Is it appropriately brief for a daily memo consumed by a busy PM?
   - 1: Essay-length, repetitive, padded with filler
   - 3: Reasonable length but some verbosity
   - 5: Tight, every sentence earns its place

5. **Analytical depth**: Does the report show critical thinking — second/third order effects, contrarian signals, moonshot bias awareness — or just surface-level summary?
   - 1: Headlines regurgitated
   - 3: Some analysis but mostly descriptive
   - 5: Non-obvious insights, connects dots the reader wouldn't have

After scoring both reports individually, provide your overall preference: which report would you rather receive as a PM at your desk each morning?

The input data used to generate both reports is provided below for fact-checking:

<input_data>
${input_data}
</input_data>
