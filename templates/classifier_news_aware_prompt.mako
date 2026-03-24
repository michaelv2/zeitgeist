<task>
You will be provided an array of questions from an online betting market.
Your job is to return only the ids of questions that are relevant to me RIGHT NOW,
given today's news headlines listed below.

A prediction is relevant if it connects to something actively happening in the news,
or if the news makes this prediction's outcome more consequential for investment decisions.
Predictions that are generically about markets but have no connection to current events are NOT relevant.
</task>

<%include file="about_me.mako"/>

<todays_headlines>
% for headline in headlines:
- ${headline}
% endfor
</todays_headlines>

Some examples of things that are UNLIKELY to be relevant (unless today's news gives a specific reason):
  - Celebrity gossip, sports outcomes, media/entertainment
  - Events far (10+ years) in the future
  - Elections in small economies unlikely to move markets
  - Memecoins and NFTs (but major crypto themes like BTC, ETH are fine)
  - Pure gambling on short-term prices (e.g. "what will ETH be at 3:05pm?")

Examine each question and return a subset of ids and related topics they may impact.
Topics must be few short strings like sectors or tickers or short phrases that would be impacted by this question.
Focus on predictions where today's news makes the outcome especially meaningful or where the prediction adds signal beyond what the headlines already say.
