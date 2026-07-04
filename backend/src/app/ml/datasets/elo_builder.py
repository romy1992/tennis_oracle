"""Rolling Elo ratings for pre-match tennis features.

Parameters (documented defaults):
- INITIAL_ELO (1500): starting rating for players without history.
- K_FACTOR (32): magnitude of post-match rating updates.
- Updates are applied only after a match result is recorded in the loop.
- Pre-match features always read ratings before the current match update.
"""

from dataclasses import dataclass

INITIAL_ELO = 1500.0
K_FACTOR = 32.0


def expected_score(rating_a: float, rating_b: float) -> float:
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400.0))


def update_elo(
    winner_elo: float,
    loser_elo: float,
    k_factor: float = K_FACTOR,
) -> tuple[float, float]:
    expected_winner = expected_score(winner_elo, loser_elo)
    expected_loser = expected_score(loser_elo, winner_elo)
    new_winner = winner_elo + k_factor * (1.0 - expected_winner)
    new_loser = loser_elo + k_factor * (0.0 - expected_loser)
    return new_winner, new_loser


@dataclass(frozen=True)
class PreMatchEloFeatures:
    player_1_elo: float
    player_2_elo: float
    elo_diff: float
    player_1_surface_elo: float
    player_2_surface_elo: float
    surface_elo_diff: float


class EloTracker:
    def __init__(
        self,
        initial_elo: float = INITIAL_ELO,
        k_factor: float = K_FACTOR,
    ) -> None:
        self.initial_elo = initial_elo
        self.k_factor = k_factor
        self._overall: dict[int, float] = {}
        self._surface: dict[tuple[int, str], float] = {}

    def get_overall(self, player_id: int) -> float:
        return self._overall.get(player_id, self.initial_elo)

    def get_surface(self, player_id: int, surface: str) -> float:
        return self._surface.get((player_id, surface), self.initial_elo)

    def pre_match_features(
        self,
        player_1_id: int,
        player_2_id: int,
        surface: str,
    ) -> PreMatchEloFeatures:
        player_1_elo = self.get_overall(player_1_id)
        player_2_elo = self.get_overall(player_2_id)
        player_1_surface_elo = self.get_surface(player_1_id, surface)
        player_2_surface_elo = self.get_surface(player_2_id, surface)
        return PreMatchEloFeatures(
            player_1_elo=player_1_elo,
            player_2_elo=player_2_elo,
            elo_diff=player_1_elo - player_2_elo,
            player_1_surface_elo=player_1_surface_elo,
            player_2_surface_elo=player_2_surface_elo,
            surface_elo_diff=player_1_surface_elo - player_2_surface_elo,
        )

    def record_match(
        self,
        player_1_id: int,
        player_2_id: int,
        surface: str,
        player_1_won: bool,
    ) -> None:
        if player_1_won:
            winner_id, loser_id = player_1_id, player_2_id
        else:
            winner_id, loser_id = player_2_id, player_1_id

        winner_overall = self.get_overall(winner_id)
        loser_overall = self.get_overall(loser_id)
        new_winner_overall, new_loser_overall = update_elo(
            winner_overall,
            loser_overall,
            self.k_factor,
        )
        self._overall[winner_id] = new_winner_overall
        self._overall[loser_id] = new_loser_overall

        winner_surface = self.get_surface(winner_id, surface)
        loser_surface = self.get_surface(loser_id, surface)
        new_winner_surface, new_loser_surface = update_elo(
            winner_surface,
            loser_surface,
            self.k_factor,
        )
        self._surface[(winner_id, surface)] = new_winner_surface
        self._surface[(loser_id, surface)] = new_loser_surface
