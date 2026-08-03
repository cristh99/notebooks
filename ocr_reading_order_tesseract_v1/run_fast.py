from rapidfuzz.distance import Levenshtein
from . import run_canary

run_canary.levenshtein = Levenshtein.distance

if __name__ == "__main__":
    run_canary.main()
