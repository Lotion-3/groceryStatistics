"""Run every analysis step end to end (spec section 6): one command.

    python run_all.py            # analysis on data/grocery.sqlite
    python run_all.py --sim      # also re-run the estimator simulations (~1 min)

Collection is deliberately NOT part of this script (it generates retailer
traffic); see README "Collecting data".
"""
from __future__ import annotations

import argparse
import sys

from analysis import coverage, module_a_tails, module_b_bayes, module_c_hd, module_d_basket, module_e_architecture


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sim", action="store_true", help="re-run simulation/validate_tail_estimators.py")
    a = ap.parse_args(argv)
    if a.sim:
        from simulation import validate_tail_estimators
        validate_tail_estimators.main()
    for mod in (coverage, module_a_tails, module_b_bayes, module_c_hd, module_d_basket, module_e_architecture):
        print(mod.run(), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
