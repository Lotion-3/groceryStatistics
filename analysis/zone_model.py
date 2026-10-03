"""Bayesian nonparametric recovery of pricing zones (Plan Q2; for Module E).

Data. For one chain: C[s, j] = which of product j's observed price levels
store s charges (0..V_j-1), or -1 if s does not carry j.

Model (Dirichlet-process mixture of product-wise categoricals):
    z_s | alpha        ~ CRP(alpha)                          zone of store s
    theta_kj           ~ Dirichlet(gamma * g_j)              zone k's price distribution for product j
    C[s, j] | z_s = k  ~ Categorical(theta_kj)               independently over carried products
    alpha              ~ Gamma(a0, b0)
g_j is the chain-wide frequency of each price level of product j (smoothed):
an EMPIRICAL-BAYES base measure, so a zone is described by how it departs from
the chain-wide pattern. (A uniform base measure over levels makes a new zone
predict every level as equally likely, which for products with many
store-specific levels made splitting practically impossible: the sampler
stayed in one zone in simulation.) gamma sets how strongly a zone's
distribution is pulled toward the chain-wide one.

Inference: collapsed Gibbs sampling (Neal 2000, Algorithm 3). theta is
integrated out, so moving store s into zone k has weight
    n_k^{-s} * prod_j (N_kj[c_sj] + gamma g_j[c_sj]) / (N_kj. + gamma)
and a new zone has weight alpha * prod_j g_j[c_sj]. alpha is updated with the
auxiliary-variable step of Escobar & West (1995).

Mixing. One-store-at-a-time Gibbs cannot split a wrongly merged zone (any
single store leaving alone looks worse than staying), which in simulation left
two true zones merged. Each sweep therefore adds sequentially-allocated
merge-split moves (Dahl 2005): pick two stores; if they share a zone, propose
splitting it by allocating its other stores one by one between the two; if
not, propose merging their zones; accept with the exact Metropolis-Hastings
ratio. Two runs from different starting partitions (all stores together; a
single-linkage partition) are compared as a convergence check.

Identifiability. Zones whose price lists are identical are observationally
the same zone (with no data to separate them the posterior simply follows the
CRP prior). Partitions are therefore summarised after merging zones whose
estimated lists (modal level per product) differ on at most LIST_TOL of the
products both carry: "distinct zones".

Summaries: posterior distribution of the number of zones (with >= 2 stores),
the posterior similarity matrix P(z_s = z_t), and a point partition (the
sampled partition with the smallest Binder loss against that matrix).

Validated on simulated price lists in simulation/validate_zone_model.py.
"""
from __future__ import annotations

import numpy as np


def encode(M, return_unique_share: bool = False):
    """Price matrix (stores x products, NaN = missing) -> (C, V).

    A price level charged by exactly ONE store is a local departure: it is
    shared with no other store, so it says nothing about which stores belong
    together. Such cells are set aside (treated as not observed) for the zone
    model; their share is returned on request and reported separately.
    (Without this, in simulation a national list plus store noise came out as
    one zone per store.)"""
    A = np.asarray(M, float)
    C = np.full(A.shape, -1, int)
    V = np.ones(A.shape[1], int)
    n_obs = n_unique = 0
    for j in range(A.shape[1]):
        col = A[:, j]
        ok = ~np.isnan(col)
        if not ok.any():
            continue
        levels, counts = np.unique(col[ok], return_counts=True)
        shared = levels[counts >= 2]
        n_obs += int(ok.sum())
        n_unique += int((counts == 1).sum())
        keep = ok & np.isin(col, shared)
        if keep.any():
            C[keep, j] = np.searchsorted(shared, col[keep])
            V[j] = len(shared)
    if return_unique_share:
        return C, V, (n_unique / n_obs if n_obs else 0.0)
    return C, V


class ZoneSampler:
    def __init__(self, C: np.ndarray, V: np.ndarray, gamma: float = 1.0, a0: float = 1.0, b0: float = 1.0,
                 seed: int = 0, init=None):
        self.C, self.V = C, V
        self.S, self.J = C.shape
        self.gamma, self.a0, self.b0 = gamma, a0, b0
        self.rng = np.random.default_rng(seed)
        self.Vmax = int(V.max())
        self.alpha = 1.0
        # empirical-Bayes base measure: smoothed chain-wide level frequencies
        G = np.zeros((self.J, self.Vmax))
        for j in range(self.J):
            col = C[:, j][C[:, j] >= 0]
            cnt = np.bincount(col, minlength=V[j]).astype(float) + 0.5
            G[j, :V[j]] = cnt / cnt.sum()
        self.G = G
        z0 = np.zeros(self.S, int) if init is None else np.unique(np.asarray(init), return_inverse=True)[1]
        self.z = z0.copy()
        self.N = np.zeros((int(z0.max()) + 1, self.J, self.Vmax))   # counts per zone, product, level
        for s in range(self.S):
            self._add(s, self.z[s])
        self.log_new = np.array([np.log(G[np.flatnonzero(C[s] >= 0), C[s][C[s] >= 0]]).sum()
                                 for s in range(self.S)])

    def _add(self, s, k, sign=1):
        obs = self.C[s] >= 0
        self.N[k, np.flatnonzero(obs), self.C[s, obs]] += sign

    def _sizes(self):
        return np.bincount(self.z, minlength=len(self.N))

    def _drop_empty(self):
        sizes = self._sizes()
        keep = np.flatnonzero(sizes > 0)
        remap = -np.ones(len(sizes), int)
        remap[keep] = np.arange(len(keep))
        self.z = remap[self.z]
        self.N = self.N[keep]

    def sweep(self):
        for s in self.rng.permutation(self.S):
            self._add(s, self.z[s], -1)
            self.z[s] = -1
            sizes = np.bincount(self.z[self.z >= 0], minlength=len(self.N))
            if (sizes == 0).any():                        # drop the zone s just emptied
                keep = np.flatnonzero(sizes > 0)
                remap = -np.ones(len(sizes), int)
                remap[keep] = np.arange(len(keep))
                self.z[self.z >= 0] = remap[self.z[self.z >= 0]]
                self.N = self.N[keep]
                sizes = sizes[keep]
            obs = np.flatnonzero(self.C[s] >= 0)
            lv = self.C[s, obs]
            num = np.log(self.N[:, obs, lv] + self.gamma * self.G[obs, lv]).sum(1)
            den = np.log(self.N[:, obs, :].sum(2) + self.gamma).sum(1)
            logw = np.append(np.log(sizes) + num - den, np.log(self.alpha) + self.log_new[s])
            w = np.exp(logw - logw.max())
            k = int(self.rng.choice(len(w), p=w / w.sum()))
            if k == len(self.N):
                self.N = np.concatenate([self.N, np.zeros((1, self.J, self.Vmax))])
            self.z[s] = k
            self._add(s, k)
        self.merge_split()
        self._update_alpha()

    # -- merge-split (Dahl 2005, sequentially allocated) -----------------
    def _logml(self, Nk: np.ndarray) -> float:
        """Collapsed log marginal likelihood of a zone with level counts Nk."""
        from scipy.special import gammaln
        g = self.gamma * self.G
        ok = self.G > 0
        tot = Nk.sum(1)
        used = tot > 0
        val = gammaln(self.gamma) - gammaln(tot + self.gamma)
        lev = np.where(ok, gammaln(Nk + np.where(ok, g, 1.0)) - gammaln(np.where(ok, g, 1.0)), 0.0).sum(1)
        return float((val + lev)[used].sum())

    def _onehot(self, s):
        out = np.zeros((self.J, self.Vmax))
        obs = self.C[s] >= 0
        out[np.flatnonzero(obs), self.C[s, obs]] = 1
        return out

    def _pred(self, s, Nk) -> float:
        obs = np.flatnonzero(self.C[s] >= 0)
        lv = self.C[s, obs]
        return float(np.log(Nk[obs, lv] + self.gamma * self.G[obs, lv]).sum()
                     - np.log(Nk[obs, :].sum(1) + self.gamma).sum())

    def _allocate(self, i, j, others, actual=None):
        """Sequential allocation of `others` between {i} and {j}. If `actual`
        (bool array: True = with i) is given, replay it and return its log
        proposal probability; else sample. Returns (side, Ni, Nj, logq)."""
        Ni, Nj = self._onehot(i), self._onehot(j)
        ni = nj = 1
        side = np.zeros(len(others), bool)
        logq = 0.0
        for t, k in enumerate(others):
            a = np.log(ni) + self._pred(k, Ni)
            b = np.log(nj) + self._pred(k, Nj)
            p_i = 1.0 / (1.0 + np.exp(np.clip(b - a, -700, 700)))
            to_i = (self.rng.random() < p_i) if actual is None else bool(actual[t])
            logq += np.log(max(p_i if to_i else 1 - p_i, 1e-300))
            side[t] = to_i
            if to_i:
                Ni += self._onehot(k); ni += 1
            else:
                Nj += self._onehot(k); nj += 1
        return side, Ni, Nj, ni, nj, logq

    def merge_split(self, n_moves: int = 10):
        from scipy.special import gammaln
        for _ in range(n_moves):
            i, j = self.rng.choice(self.S, 2, replace=False)
            zi, zj = self.z[i], self.z[j]
            if zi == zj:
                others = self.rng.permutation(np.flatnonzero((self.z == zi) & (np.arange(self.S) != i)
                                                            & (np.arange(self.S) != j)))
                side, Ni, Nj, ni, nj, logq = self._allocate(i, j, others)
                log_r = (np.log(self.alpha) + gammaln(ni) + gammaln(nj) - gammaln(ni + nj)
                         + self._logml(Ni) + self._logml(Nj) - self._logml(self.N[zi]) - logq)
                if np.log(self.rng.random()) < log_r:
                    new = len(self.N)
                    self.N = np.concatenate([self.N, Nj[None]])
                    self.N[zi] = Ni
                    self.z[others[~side]] = new
                    self.z[j] = new
            else:
                members = np.flatnonzero(((self.z == zi) | (self.z == zj)) & (np.arange(self.S) != i)
                                         & (np.arange(self.S) != j))
                others = self.rng.permutation(members)
                actual = self.z[others] == zi
                _, _, _, ni, nj, logq = self._allocate(i, j, others, actual=actual)
                merged = self.N[zi] + self.N[zj]
                log_r = (-np.log(self.alpha) - gammaln(ni) - gammaln(nj) + gammaln(ni + nj)
                         + self._logml(merged) - self._logml(self.N[zi]) - self._logml(self.N[zj]) + logq)
                if np.log(self.rng.random()) < log_r:
                    self.N[zi] = merged
                    self.z[self.z == zj] = zi
                    self.N[zj] = 0
                    self._drop_empty()

    def _update_alpha(self):
        """Escobar & West (1995) auxiliary-variable update of alpha."""
        K, n = len(self.N), self.S
        eta = self.rng.beta(self.alpha + 1, n)
        odds = (self.a0 + K - 1) / (n * (self.b0 - np.log(eta)))
        shape = self.a0 + K if self.rng.random() < odds / (1 + odds) else self.a0 + K - 1
        self.alpha = self.rng.gamma(shape, 1.0 / (self.b0 - np.log(eta)))


LIST_TOL = 0.005      # zones whose lists differ on <= 0.5% of shared products are one zone


def merge_identical(C: np.ndarray, z: np.ndarray, tol: float = LIST_TOL) -> np.ndarray:
    """Merge zones whose estimated price lists (modal level per product among
    the zone's stores) differ on at most `tol` of the products both carry."""
    labels = np.unique(z)
    modal = {}
    for k in labels:
        Ck = C[z == k]
        m = np.full(C.shape[1], -1)
        for jj in range(C.shape[1]):
            col = Ck[:, jj][Ck[:, jj] >= 0]
            if len(col):
                m[jj] = np.bincount(col).argmax()
        modal[k] = m
    parent = {k: k for k in labels}

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k
    for a_i, a in enumerate(labels):
        for b in labels[a_i + 1:]:
            both = (modal[a] >= 0) & (modal[b] >= 0)
            if both.sum() >= 20 and (modal[a][both] != modal[b][both]).mean() <= tol:
                parent[find(a)] = find(b)
    return np.unique([find(k) for k in z], return_inverse=True)[1]


def distinct_zones(C: np.ndarray, z: np.ndarray, min_size: int = 2) -> int:
    m = merge_identical(C, z)
    return int((np.bincount(m) >= min_size).sum())


def single_linkage_start(C: np.ndarray, t: float = 0.02) -> np.ndarray:
    """Data-driven starting partition: stores linked if they differ on at most
    a share t of shared products (connected components)."""
    from scipy.sparse.csgraph import connected_components
    ok = C >= 0
    S = len(C)
    adj = np.zeros((S, S), int)
    for i in range(S):
        both = ok[i] & ok
        n = both.sum(1)
        diff = ((C[i] != C) & both).sum(1)
        adj[i] = (n >= 20) & (diff <= t * np.maximum(n, 1))
    np.fill_diagonal(adj, 0)
    return connected_components(adj, directed=False)[1]


def _run(C, V, n_sweeps, burn, thin, gamma, seed, init):
    sm = ZoneSampler(C, V, gamma=gamma, seed=seed, init=init)
    parts, alphas, k_ge2 = [], [], []
    for it in range(n_sweeps):
        sm.sweep()
        if it >= burn and (it - burn) % thin == 0:
            parts.append(sm.z.copy())
            alphas.append(sm.alpha)
            k_ge2.append(distinct_zones(C, sm.z))
    return parts, alphas, k_ge2


def fit_zones(M, n_sweeps: int = 1500, burn: int = 500, thin: int = 5, gamma: float = 1.0, seed: int = 0) -> dict:
    """Two runs (all-together start; single-linkage start), pooled for the
    summaries; their point partitions are compared (ARI) as a check."""
    C, V = encode(M)
    runs = [_run(C, V, n_sweeps, burn, thin, gamma, seed, None),
            _run(C, V, n_sweeps, burn, thin, gamma, seed + 1, single_linkage_start(C))]
    S = len(C)

    def psm(parts):
        P = np.zeros((S, S))
        for z in parts:
            P += z[:, None] == z[None, :]
        return P / len(parts)

    def binder(parts, P):
        return parts[int(np.argmin([np.abs((z[:, None] == z[None, :]) - P).sum() for z in parts]))]

    per_run = [merge_identical(C, binder(r[0], psm(r[0]))) for r in runs]
    parts = runs[0][0] + runs[1][0]
    P = psm(parts)
    return {"psm": P, "partition": merge_identical(C, binder(parts, P)),
            "k_ge2": np.array(runs[0][2] + runs[1][2]),
            "alpha": np.array(runs[0][1] + runs[1][1]), "n_kept": len(parts), "gamma": gamma,
            "start_agreement_ari": adjusted_rand(per_run[0], per_run[1]),
            "k_ge2_by_start": (float(np.mean(runs[0][2])), float(np.mean(runs[1][2])))}


def adjusted_rand(a: np.ndarray, b: np.ndarray) -> float:
    """Adjusted Rand index between two partitions."""
    from math import comb
    ct = {}
    for x, y in zip(a, b):
        ct[(x, y)] = ct.get((x, y), 0) + 1
    sum_ij = sum(comb(v, 2) for v in ct.values())
    sa = sum(comb(int(v), 2) for v in np.bincount(np.unique(a, return_inverse=True)[1]))
    sb = sum(comb(int(v), 2) for v in np.bincount(np.unique(b, return_inverse=True)[1]))
    n2 = comb(len(a), 2)
    exp = sa * sb / n2
    mx = (sa + sb) / 2
    return float((sum_ij - exp) / (mx - exp)) if mx != exp else 1.0
