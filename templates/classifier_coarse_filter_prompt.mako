<task>
You will be provided an array of questions from an online betting market.
Your job is to REMOVE only the obviously irrelevant ones and keep everything else.
Return the ids of questions that MIGHT be relevant to an investment professional.

This is a coarse filter — when in doubt, INCLUDE the prediction. Err on the side of keeping too many rather than too few. A downstream system will handle fine-grained relevance.
</task>

Remove ONLY predictions that are clearly about:
  - Sports outcomes (game scores, player trades, championships, MVPs)
  - Celebrity gossip, entertainment, media (billboard charts, album releases, TV shows)
  - Pure short-term price gambling with no analytical value (e.g. "ETH up or down in next 5 minutes")
  - Novelty/meme bets (e.g. "Will Jesus return before GTA VI?")

KEEP anything that could plausibly relate to:
  - Economics, policy, regulation, trade, geopolitics, technology, energy, crypto trends, corporate activity, elections in major economies, or market structure

Examine each question and return the ids and a brief topic tag for each.
Topics must be few short strings like sectors or tickers or short phrases.
