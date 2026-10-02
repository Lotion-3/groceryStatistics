# Vendored collectors

Copied verbatim from the owner's basketBuddy repo, `backend/` directory, at commit
`9310f751cd1b3278fb5b31f289067c3b2fc04254` on 2026-10-01. **Do not edit these files**:
keeping them byte-identical makes it possible to verify that the research data came
from the same code as the production app. This project's own logic lives one directory up
in `collectors/` and only calls into these modules.

## Deviations from upstream

- `session_store.py` is a **stub** written for this project. The upstream module talks to the
  production Supabase project, which this project must never touch. The original is kept as
  `session_store_supabase_original.py.txt` for reference (it holds no secrets).
- `db.py` was deliberately not copied (only the original session_store imported it).
- No session / cookie / asset-cache files were copied. They are re-minted locally on first use
  and are gitignored (see the repo's `.gitignore`).

## Files used by this project's wrappers

walmart_pricing, target_pricing, instacart_pricing (Costco), trader_joes_pricing, kroger_pricing
(size parsing), kroger_search_map, pricing_pool, browser_gate, walmart_warm_subprocess,
walmart_store_graphql.json, target_store_directory.json.

## Copied for completeness only (no wrappers)

aldi/aldi_pricing, meijer_pricing, kroger_async, kingsoopers_pricing, iga_pricing,
mint_walmart_cookies, build_target_store_directory.

## SHA-256 of the files as copied

```
33dbd5c4e219c9dd83fa07cf3052d20214547fb16885f7f9270fe6567afec57f *./aldi/aldi_pricing.py
72b1d411a53bd8587d0d91cd5f5c78dbc6c9803cbe2d5925cc07b88ec17d3a35 *./browser_gate.py
2fbef72e3fbc8ead84939f1138bbc11d4c1a074742019339758716f27281ff45 *./build_target_store_directory.py
df8a36aa71a7816f68cd8a7a6b325414cdeaf26f8db679fbac992ef5f80ac8d4 *./iga_pricing.py
09d069740dd8114dc344c15b03dbf574fff1d43c696d2897ee35e61cd55a25d1 *./instacart_pricing.py
e70e4ea32fdc4b15d8820677fe91075b37efb64610cd5bccc723d71d4802d2c8 *./kingsoopers_pricing.py
a4c73b9c920bfa23062c9664b76a5092eb446cd144aded9a8dc650c0ffec1e74 *./kroger_async.py
ae7955fa9417f61eabc4ee02693ba213fae2d3af0bcc20ae00a0a0339dc1a82e *./kroger_pricing.py
2a4fd0d8f8e3f8405a79adb428ccf987fac01724227545be47e5bfebb8087062 *./kroger_search_map.py
b3417177266b8c0009cd1b9a599b4f89a29749174b036485d97ffb20236bf150 *./meijer_pricing.py
ee1ecddb9510ae984e8a4fd2f08c235487ffacb742846038c5c75cebbaf22353 *./mint_walmart_cookies.py
feb7184d6b5b84e3214b035daec0e5f8af6b6eaac3ed90aa25627fd49772be16 *./pricing_pool.py
eb093934bcee6f95ab080d7bc402437454b997387f9281662c58d467068aff61 *./session_store_supabase_original.py.txt
7c3dac01cf9ef6993c7a6b1565c2049637d7305f0af9b9f92854adb101091c81 *./target_pricing.py
477dc71d9ed4c017cb5f48dcec36fb546cbaf5d27b3b6477a2dc76580ec5cbb5 *./target_store_directory.json
bd78e862e3ac6250de0e39a7e16ced2634920661b9ddc6a66cb51197317786d0 *./trader_joes_pricing.py
31957b996a1a4cd95d6c25176cb1759fc945c10e52a816fd7325915dd60effae *./walmart_pricing.py
9540215565daefa9e54ee1ceb4114b487a890d7b36d727322846a3cf34ab4797 *./walmart_store_graphql.json
cd4649776555386e98f60a6d89103ef7b87b39b16742db4672e6a5eefde1a61f *./walmart_warm_subprocess.py
```
