"""Contract tests for the exact null used to compare duplicate pass rates.

The inferential claim in ER-9ad782d0 rests on these moments being right, so they are
checked against brute-force enumeration rather than against a remembered number.
"""

import sys
from itertools import product
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from check_dolci_dispersion import gap_distribution, gap_moments  # noqa: E402
from check_dolci_references import occupied_rooms, ordered_pairs_mod_81  # noqa: E402


def brute_force(successes, rollouts):
    """Enumerate every equally likely assignment of outcomes to two copies.

    Conditional on the total, each arrangement of `successes` correct rollouts among
    the 2 * rollouts slots is equally likely regardless of the pass rate, which is why
    the null needs no estimate of it.
    """
    gaps = {}
    total = 0
    for slots in product((0, 1), repeat=2 * rollouts):
        if sum(slots) != successes:
            continue
        gap = abs(sum(slots[:rollouts]) - sum(slots[rollouts:]))
        gaps[gap] = gaps.get(gap, 0) + 1
        total += 1
    return {gap: count / total for gap, count in gaps.items()}


class GapNullTests(unittest.TestCase):
    def test_distribution_matches_brute_force(self):
        for rollouts in (3, 4):
            for successes in range(2 * rollouts + 1):
                with self.subTest(rollouts=rollouts, successes=successes):
                    expected = brute_force(successes, rollouts)
                    actual = gap_distribution(successes, rollouts)
                    self.assertEqual(sorted(expected), sorted(actual))
                    for gap, probability in expected.items():
                        self.assertAlmostEqual(probability, actual[gap])

    def test_moments_match_the_distribution(self):
        for successes in range(17):
            mean, variance = gap_moments(successes, 8, 8)
            distribution = gap_distribution(successes, 8)
            self.assertAlmostEqual(mean, sum(g * p for g, p in distribution.items()))
            self.assertAlmostEqual(variance + mean * mean,
                                   sum(g * g * p for g, p in distribution.items()))

    def test_a_shared_total_of_zero_or_everything_forces_agreement(self):
        for successes in (0, 16):
            self.assertEqual((0.0, 0.0), gap_moments(successes, 8, 8))

    def test_an_odd_total_cannot_produce_an_even_gap(self):
        self.assertEqual([1, 3, 5, 7], sorted(gap_distribution(7, 8)))

    def test_unequal_rollout_counts_are_supported(self):
        mean, variance = gap_moments(5, 5, 8)
        self.assertGreater(mean, 0)
        self.assertGreater(variance, 0)


class ReferenceAnswerTests(unittest.TestCase):
    """The two answers that ER-a3060c49 calls six published labels wrong against."""

    def test_ordered_pairs_mod_81(self):
        self.assertEqual(45, ordered_pairs_mod_81())

    def test_occupied_rooms_after_an_hour(self):
        self.assertEqual(31, occupied_rooms())

    def test_simulation_conserves_people_and_tracks_a_small_case(self):
        # One person never moves, so exactly one room stays occupied.
        self.assertEqual(1, occupied_rooms(rooms=10, people=1, minutes=5))
        # Two people in room 1: one steps to room 2 on the first minute, then both stay.
        self.assertEqual(2, occupied_rooms(rooms=10, people=2, minutes=5))


if __name__ == "__main__":
    unittest.main()
