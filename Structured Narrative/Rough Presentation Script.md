# Rough Presentation Script
**Structured Narrative Model — progress since Thursday, Jul 16**

*(Note: I couldn't find last week's actual script file anywhere to match its exact phrasing/pacing, so this is written fresh in the same conversational, walk-through style as the slide deck. Adjust freely.)*

---

## Opening / recap

"Quick recap of where we were last Thursday: we had the 4-name pilot running — Amazon, Microsoft, Nvidia, and Apple — with narrative dimension scores from the earnings calls joined to a point-in-time quant spine, and a first pass at a cross-company evaluation framework. I'd sent that evaluation over for a read, and got back some really useful feedback — five specific things. I want to walk through what I did with each of them, because together they basically rewrote how we test whether this model's signal is real."

## The feedback, and why it mattered

"The most important one first: the sample sizes in my Rank IC output were showing 32 observations per period, even though we only have 4 companies. That's because I was treating each company's 8 dimension rows — demand, margins, guidance, and so on — as 8 separate observations, when really they all point back to the *same* company return. So I was quietly inflating my sample size by 8x. That's not a small bug — it's exactly the kind of thing that can make a mediocre signal look statistically significant when it isn't. Fixing that came first, before anything else, because every other number in this deck depends on it being right."

"The other four asks were: use the common 'as-of' cross-sectional construction as the primary test rather than the event-date version; if I keep the event version, bucket it by actual earnings date rather than fiscal quarter label, since those aren't calendar-aligned across companies; add a proper mean-return comparison with a bootstrap confidence interval for the agreement signal, since it's categorical; and add multiple forward horizons so we can tell if any effect is immediate, delayed, or persistent."

## What I built

"I implemented all five. Rank IC is now computed separately for each period-and-dimension pair — never pooled across dimensions — so you can look at Demand, Margins, or Guidance completely independently, which was the specific ask. The 'as-of' label is now the default primary test, and the event-date version buckets by the actual earnings date instead of the fiscal label. The agreement signal now reports mean return for agree-versus-disagree, the spread between them, and a 95% bootstrap confidence interval that resamples at the *ticker* level — same fix as the unit-of-observation issue, just applied to a mean instead of a correlation. And I added four new forward-return windows — the first two weeks after entry, the next three weeks, the three weeks after that, and the full nine-week combined window — computed offline from the cached daily returns, on top of the original 90-day window we already had."

## The interesting result

"Here's where it actually gets interesting. Once I had multiple horizons, two patterns popped out immediately. First: the narrative *tone-change* signal — how much more positive or negative management sounded quarter over quarter — has a Rank IC of plus 0.135 in the first three weeks after the call, and then flips to *negative* 0.13 in the following three weeks. That's about as clean an example of 'immediate versus delayed' as you could ask for — it looks like short-term overreaction that reverses, not a durable edge."

"Second, and I think more useful: the agreement signal — whether the narrative and the quant surprise point the same direction — does the *opposite*. It's basically flat in the first three weeks, but builds to a Rank IC of 0.10 by week six to nine, and 0.17 by the ~90-day mark. The mean-return spread tells the same story in dollar terms: near zero right after the call, growing to about 9 basis points by day 43 to 63, and 29 basis points by day 90. So the read is: the market doesn't seem to price narrative-quant agreement right away — it shows up as a slow drift over the quarter, while pure tone changes look more like noise that reverses. That's a genuinely new finding this week, not something we could have said before the multi-horizon work."

## The unglamorous half — data hygiene

"Separately from the evaluation framework, I also had to clean up a few data issues that would have quietly undermined all of this if left alone. Nvidia's fiscal quarters were bucketing into the wrong calendar quarter — fixed that with a proper nearest-calendar-quarter-end rule. I trimmed every company's history to the same five-year, 2021-Q3-onward window so it's a genuinely apples-to-apples four-name comparison, not Amazon's longer history quietly skewing things. And I recovered three quarters — two from a registry flag mismatch, and Nvidia's Q4-2024 specifically, which needed a transcript I didn't have until this week, plus fixing a real pipeline bug where force-rescoring one quarter was silently dropping other quarters' scores on merge. Net result: the numbers I just walked through are running on a clean, gap-free, consistently-aligned panel."

## New this week — the composite signal

"The last piece is new: I built a composite signal that blends the six existing narrative and quant signals into a single number per dimension. It's fit walk-forward — every weight is based only on that signal's own track record in *prior* periods, so there's no lookahead. A signal that's been reliable gets more weight; one that's been consistently backwards gets flipped and used contrarian; one without enough history yet gets close to zero weight. I deliberately left out two inputs: evidence-confidence, because it turns out to be constant at 1.0 across every row right now — it's a dead signal until the evidence-verification step can produce partial scores — and the delayed guidance-revision signal, which is a different timing scope."

"Where does it land? At the immediate horizon it's actually quite competitive — plus 0.115 Rank IC, second only to the raw tone-change signal's 0.135. Further out it's more mixed. And I want to be upfront about that: with only 4 tickers and about 20 periods, the fitted weights are themselves noisy, so a mixed result at longer horizons is the expected, honest outcome of walk-forward fitting on a small sample — not something I'm trying to paper over. Every weight it produces is fully visible in the report, so it's not a black box."

## Why this matters

"Stepping back — the whole point of this model is to answer one question: does a disciplined, evidence-backed read of the earnings call tell you something the point-in-time quant numbers don't already tell you? Everything this week was in service of being able to answer that honestly. The unit-of-observation fix means every number I show you now is trustworthy rather than artificially inflated. The horizon and agreement-effect work is the first real evidence of *when* a narrative-based signal would actually need to be timed. And the composite signal is the first attempt at what the eventual deliverable actually looks like — one point-in-time-legal score per dimension, built only from inputs that have proven themselves so far."

## Where we go next

"Next up: the single biggest lever right now is expanding past 4 names — that's what's driving the wide confidence intervals and the noisy composite weights, and it's the fastest way to know if what I'm seeing is real. I also want to dig into why the tone-change signal reverses — real overreaction, or small-sample noise. And I want to get evidence-confidence a real rubric so it's not a dead input. Happy to take questions."
