from rapidfuzz.distance import Levenshtein
from . import run_canary

run_canary.levenshtein = Levenshtein.distance

from . import verify_report

if __name__ == "__main__":
    verify_report.main()
