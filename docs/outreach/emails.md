# Draft emails (edit before sending)

The event result is filled in (Lee's email). Fill in **[PAPER]** yourself with a paper of
theirs that you have actually read. A specific sentence about it is the most important
part of each email. Keep each email to about 150 words, attach `one_pager.md` as a PDF, and
link the repository.

---

## Prof. Lee (market microstructure, arbitrage, Hawkes processes)

Subject: Undergraduate project on retail price-update microstructure

Dear Professor Lee,

I am a Purdue undergraduate interested in joining your group. Over the past week I built
a dataset of store-level grocery prices across six US chains, including Kroger's
per-store price timestamps. The timestamps show that a chain updates its prices in
batches by pricing zone: within a zone, stores receive each update in store-number order,
almost always overnight. I also ran a pre-registered event study around a scheduled
nationwide promotion expiry. Nine of ten predictions held: the expiry was enforced within
16 minutes, and the event night had 46 times the normal change rate. One failed: zones did
not share the exact switch minute.

Reading **[PAPER]**, I wondered whether a mutually exciting point-process model could
describe how these batches propagate across zones. Would you have time to talk about
whether there is a place for me in your group? A one-page summary is attached.

Best regards,
Laksh Agarwal

---

## Prof. Rao (Bayesian nonparametrics, MCMC)

Subject: Dirichlet-process zone model for retail pricing (undergraduate project)

Dear Professor Rao,

I am a Purdue undergraduate hoping to do research in Bayesian nonparametrics. For a
project on how retail chains organise prices across stores, I fitted a Dirichlet-process
mixture over store price lists. I used collapsed Gibbs with merge–split moves and an
empirical-Bayes base measure, validated it on simulated data, and checked it by
split-half replication. Without seeing any labels, it recovers Kroger's operating
divisions (95% purity). The posterior is clearly overconfident, because products are
treated as independent within a zone, and I would like to learn better ways to handle
that dependence.

After reading **[PAPER]**, I would value your view on this. Is there room in your group
for an undergraduate? A one-page summary is attached.

Best regards,
Laksh Agarwal

---

## Prof. Owada (heavy tails, extreme-value theory, random graphs, topological data analysis)

Subject: Heavy tails and truncation in retail price data (undergraduate project)

Dear Professor Owada,

I am a Purdue undergraduate interested in extreme-value and topological methods. In a
project on store-level grocery prices, I estimated departure tails (Hill and
generalised-Pareto, with store-cluster bootstrap; the extreme tail turns out to be mostly
geographic). I also found that the sizes of price-update batches are heavy-tailed, and
used persistent homology to look for pricing zones. One part I found especially
interesting: from a single snapshot, four estimators of promotion length (naive, renewal,
length-bias, and Lynden-Bell for left-truncated data) disagree, and a simulation explains
why.

Having read **[PAPER]**, I would like to ask whether you take undergraduate researchers. A
one-page summary is attached.

Best regards,
Laksh Agarwal

---

## Prof. Song (high-dimensional statistics, Bayesian computing, optimisation)

Subject: High-dimensional and Bayesian analysis of retail pricing (undergraduate project)

Dear Professor Song,

I am a Purdue undergraduate interested in high-dimensional statistics and Bayesian
computation. In a project on how chains price identical products across about 700
stores, I compared a regularised horseshoe with lasso and elastic net, using
state-blocked cross-validation on about 130 covariates. Demographics turn out to predict
little; location matters through the chain's zone design. I also fitted Gaussian-process
spatial models with NUTS, a hierarchical binomial model for pairs of stores, and an
integer program for basket arbitrage.

After reading **[PAPER]**, I would be glad to hear whether there is an opportunity to
contribute to your group. A one-page summary is attached.

Best regards,
Laksh Agarwal
