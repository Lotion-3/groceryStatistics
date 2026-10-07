**Kroger (pre-registered H1-H7; passes {'control': 6, 'before': 10, 'probe_pre': 14, 'probe_post': 15, 'probe_early': 16, 'after': 19})**

| | Prediction | Value | n | Holds |
|---|---|---|---|---|
| H1 | old promotion gone in after >= 0.95 | 1.000 | 1,950 | yes |
| H2 | price-change rate: scheduled >= 0.80 | 0.917 | 1,950 | yes |
| H2 | price-change rate: not scheduled <= 0.15 | 0.135 | 14,014 | yes |
| H5 | new prices effective before the expiry >= 0.15 | 0.012 | 1,950 | **no** |
| H5 | new prices effective Wed 04:00-11:00 ET >= 0.50 | 0.906 | 1,950 | yes |
| H3 | change rate before->after >= 3 x control->before | 42.069 | 15,964 | yes |
| H4 | probe_pre: scheduled promotions still present >= 0.90 | 1.000 | 979 | yes |
| H4 | probe_post: scheduled promotions gone >= 0.90 | 1.000 | 975 | yes |
| H6a | H6a_same_effective_minute: within zone > across zone (one-sided p < 0.05) | 0.093 | 20,958 | yes |
| H6b | H6b_same_new_price: within zone > across zone (one-sided p < 0.05) | 0.216 | 20,958 | yes |

**Meijer (Addendum 4, M1-M4; passes {'control': 7, 'before': 12, 'after': 17})**

| | Prediction | Value | n | Holds |
|---|---|---|---|---|
| M1 | change rate of scheduled units >= 0.80 | 0.371 | 860 | **no** |
| M2 | change rate of other units <= 0.15 | 0.025 | 15,632 | yes |
| M3 | change rate before->after >= 3 x control->before | 53.661 | 16,492 | yes |
| M4 | products with one new price across stores >= 0.90 | 0.652 | 66 | **no** |
