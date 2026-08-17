import unittest

from backend.src.app.ml.datasets.score_parser import (
    FixtureScoreRecord,
    SCORE_TARGET_COLUMNS,
    _summarize_records,
    parse_event_game_result_text,
    parse_fixture_score,
    parse_scores_json,
    score_targets_from_parsed,
    target_over_line,
)


def _api_tennis_scores(*sets: tuple[str, str]) -> list[dict]:
    labels = ["1st Set", "2nd Set", "3rd Set", "4th Set", "5th Set"]
    return [
        {"score_first": p1, "score_second": p2, "score_set": labels[index]}
        for index, (p1, p2) in enumerate(sets)
    ]


def _real_provider_scores(*sets: tuple[str, str]) -> list[dict]:
    """Formato REALE confermato sul DB di produzione: ``score_set`` e' una
    stringa numerica semplice ("1","2","3"...), non "1st Set"."""
    return [
        {"score_first": p1, "score_second": p2, "score_set": str(index + 1)}
        for index, (p1, p2) in enumerate(sets)
    ]


class ParseScoresJsonTest(unittest.TestCase):
    def test_straight_sets_win_player_1(self):
        payload = _api_tennis_scores(("6", "4"), ("7", "5"))
        parsed = parse_scores_json(payload, match_id=1)

        self.assertEqual(parsed.parse_source, "scores_json")
        self.assertEqual(parsed.sets_played, 2)
        self.assertEqual(parsed.sets_won_player_1, 2)
        self.assertEqual(parsed.sets_won_player_2, 0)
        self.assertEqual(parsed.first_set_winner, "player_1")
        self.assertEqual(parsed.correct_score_label, "2-0")
        self.assertTrue(parsed.is_straight_sets)
        self.assertEqual(parsed.total_games, 22)
        self.assertTrue(parsed.is_valid_for_training)

    def test_three_set_win_player_2_first_set_lost_by_player_1(self):
        payload = _api_tennis_scores(("6", "4"), ("3", "6"), ("4", "6"))
        parsed = parse_scores_json(payload, match_id=2)

        self.assertEqual(parsed.first_set_winner, "player_1")
        self.assertEqual(parsed.sets_won_player_1, 1)
        self.assertEqual(parsed.sets_won_player_2, 2)
        self.assertEqual(parsed.correct_score_label, "1-2")
        self.assertFalse(parsed.is_straight_sets)
        self.assertTrue(parsed.is_valid_for_training)

    def test_tiebreak_set_is_valid(self):
        payload = _api_tennis_scores(("7", "6"), ("6", "3"))
        parsed = parse_scores_json(payload, match_id=3)

        self.assertTrue(parsed.is_valid_for_training)
        self.assertEqual(parsed.total_games_player_1, 13)
        self.assertEqual(parsed.total_games_player_2, 9)

    def test_none_or_null_literal_payload_returns_none(self):
        self.assertIsNone(parse_scores_json(None, match_id=1))
        self.assertIsNone(parse_scores_json("null", match_id=1))
        self.assertIsNone(parse_scores_json([], match_id=1))

    def test_out_of_order_set_labels_are_sorted(self):
        payload = [
            {"score_first": "3", "score_second": "6", "score_set": "2nd Set"},
            {"score_first": "6", "score_second": "4", "score_set": "1st Set"},
        ]
        parsed = parse_scores_json(payload, match_id=4)

        self.assertEqual(parsed.sets[0].player_1_games, 6)
        self.assertEqual(parsed.sets[1].player_1_games, 3)

    def test_retirement_mid_set_is_excluded_from_training(self):
        # Ultimo set incompleto (ritiro a 3-2): punteggio non valido per un set concluso.
        payload = _api_tennis_scores(("6", "4"), ("3", "2"))
        parsed = parse_scores_json(payload, match_id=5)

        self.assertTrue(parsed.has_anomalous_set)
        self.assertTrue(parsed.is_suspected_retirement)
        self.assertFalse(parsed.is_valid_for_training)

    def test_retirement_after_one_set_omitted_from_provider_is_excluded(self):
        # Il provider a volte omette del tutto l'ultimo set incompleto: i set
        # superstiti sembrano individualmente validi ma il conteggio totale
        # (1-0) non corrisponde a un match concluso best-of-3/5.
        payload = _api_tennis_scores(("6", "4"))
        parsed = parse_scores_json(payload, match_id=6)

        self.assertFalse(parsed.has_anomalous_set)
        self.assertFalse(parsed.has_valid_match_shape)
        self.assertTrue(parsed.is_suspected_retirement)
        self.assertFalse(parsed.is_valid_for_training)

    def test_non_dict_entries_and_non_numeric_games_are_skipped_with_warning(self):
        payload = ["not-a-dict", {"score_first": "abc", "score_second": "4"}]
        parsed = parse_scores_json(payload, match_id=7)

        self.assertEqual(parsed.sets_played, 0)
        self.assertIn("entry_0_not_dict", parsed.warnings)
        self.assertIn("entry_1_non_numeric_games", parsed.warnings)

    def test_trailing_zero_zero_placeholder_slots_are_skipped_not_anomalous(self):
        # Formato reale confermato in produzione: l'array ha lunghezza fissa
        # (fino a 5 slot); i set oltre quelli disputati sono "0"-"0".
        payload = _real_provider_scores(("6", "3"), ("6", "4"), ("0", "0"), ("0", "0"), ("0", "0"))
        parsed = parse_scores_json(payload, match_id=8)

        self.assertEqual(parsed.sets_played, 2)
        self.assertFalse(parsed.has_anomalous_set)
        self.assertTrue(parsed.has_valid_match_shape)
        self.assertTrue(parsed.is_valid_for_training)
        self.assertEqual(parsed.correct_score_label, "2-0")
        self.assertEqual(len([w for w in parsed.warnings if "zero_zero_unplayed_slot_skipped" in w]), 3)

    def test_tiebreak_set_encoded_as_games_dot_tiebreak_points(self):
        # Formato reale confermato in produzione: set al tiebreak codificato
        # come "game.punti_tiebreak" (es. "7.7" = 7 game, tiebreak 7 punti).
        payload = _real_provider_scores(("7.7", "6.2"), ("6", "4"))
        parsed = parse_scores_json(payload, match_id=9)

        self.assertEqual(parsed.sets[0].player_1_games, 7)
        self.assertEqual(parsed.sets[0].player_2_games, 6)
        self.assertTrue(parsed.sets[0].is_valid)
        self.assertTrue(parsed.is_valid_for_training)
        self.assertEqual(parsed.correct_score_label, "2-0")

    def test_extended_tiebreak_decimal_both_sides(self):
        # Tiebreak esteso vinto 9-7: entrambi i lati portano il decimale.
        payload = _real_provider_scores(("7.9", "6.7"))
        parsed = parse_scores_json(payload, match_id=10)

        self.assertEqual(parsed.sets[0].player_1_games, 7)
        self.assertEqual(parsed.sets[0].player_2_games, 6)


class ParseEventGameResultTextTest(unittest.TestCase):
    def test_marked_as_experimental_source_and_excluded_from_training(self):
        parsed = parse_event_game_result_text("6-4, 7-5", match_id=1)

        self.assertEqual(parsed.parse_source, "event_game_result_regex")
        self.assertEqual(parsed.sets_played, 2)
        # Sempre escluso dal training finche' non verificato empiricamente.
        self.assertFalse(parsed.is_valid_for_training)

    def test_tiebreak_suffix_is_ignored(self):
        parsed = parse_event_game_result_text("7-6(4) 6-3", match_id=2)

        self.assertEqual(parsed.sets[0].player_1_games, 7)
        self.assertEqual(parsed.sets[0].player_2_games, 6)

    def test_no_tokens_found(self):
        parsed = parse_event_game_result_text("in progress", match_id=3)
        self.assertEqual(parsed.sets_played, 0)

    def test_blank_or_none_returns_none(self):
        self.assertIsNone(parse_event_game_result_text(None, match_id=1))
        self.assertIsNone(parse_event_game_result_text("   ", match_id=1))


class ParseFixtureScoreTest(unittest.TestCase):
    def test_prefers_scores_json_over_text_fallback(self):
        parsed = parse_fixture_score(
            match_id=1,
            scores=_api_tennis_scores(("6", "4"), ("6", "3")),
            event_game_result="1-6, 3-6",
            allow_text_fallback=True,
        )
        self.assertEqual(parsed.parse_source, "scores_json")

    def test_falls_back_to_text_only_when_enabled(self):
        parsed_disabled = parse_fixture_score(
            match_id=1, scores=None, event_game_result="6-4, 7-5", allow_text_fallback=False
        )
        parsed_enabled = parse_fixture_score(
            match_id=1, scores=None, event_game_result="6-4, 7-5", allow_text_fallback=True
        )
        self.assertEqual(parsed_disabled.parse_source, "none")
        self.assertEqual(parsed_enabled.parse_source, "event_game_result_regex")

    def test_no_data_at_all(self):
        parsed = parse_fixture_score(match_id=1, scores=None, event_game_result=None)
        self.assertEqual(parsed.parse_source, "none")
        self.assertFalse(parsed.is_valid_for_training)


class ScoreTargetsFromParsedTest(unittest.TestCase):
    def test_valid_match_produces_all_targets(self):
        parsed = parse_scores_json(_api_tennis_scores(("6", "4"), ("7", "5")), match_id=42)
        assert parsed is not None
        targets = score_targets_from_parsed(parsed)

        self.assertEqual(targets["match_id"], 42)
        self.assertTrue(targets["score_is_valid_for_training"])
        self.assertEqual(targets["target_first_set_winner"], 1)
        self.assertEqual(targets["target_sets_won_player_1"], 2)
        self.assertEqual(targets["target_sets_won_player_2"], 0)
        self.assertEqual(targets["target_correct_score_sets"], "2-0")
        self.assertTrue(targets["target_straight_sets"])
        self.assertEqual(targets["target_total_games"], 22)
        for column in SCORE_TARGET_COLUMNS:
            self.assertIn(column, targets)

    def test_invalid_match_produces_none_targets_not_defaults(self):
        parsed = parse_scores_json(_api_tennis_scores(("6", "4"), ("3", "2")), match_id=43)
        assert parsed is not None
        targets = score_targets_from_parsed(parsed)

        self.assertFalse(targets["score_is_valid_for_training"])
        for column in SCORE_TARGET_COLUMNS:
            self.assertIsNone(targets[column])


class TargetOverLineTest(unittest.TestCase):
    def test_over_and_under(self):
        self.assertEqual(target_over_line(23, 22.5), 1)
        self.assertEqual(target_over_line(22, 22.5), 0)

    def test_none_total_games(self):
        self.assertIsNone(target_over_line(None, 22.5))


class SummarizeRecordsTest(unittest.TestCase):
    def test_orientation_agreement_detected(self):
        records = [
            FixtureScoreRecord(
                match_id=1,
                scores=_api_tennis_scores(("6", "4"), ("6", "3")),
                event_game_result=None,
                event_winner="First Player",
            ),
            FixtureScoreRecord(
                match_id=2,
                scores=_api_tennis_scores(("4", "6"), ("3", "6")),
                event_game_result=None,
                event_winner="Second Player",
            ),
        ]
        report = _summarize_records(records)

        self.assertEqual(report["total_completed_fixtures"], 2)
        self.assertEqual(report["orientation_check"]["agree_with_event_winner"], 2)
        self.assertEqual(report["orientation_check"]["disagree_with_event_winner"], 0)
        self.assertEqual(report["orientation_check"]["agreement_pct"], 100.0)
        self.assertEqual(report["valid_for_training"], 2)

    def test_orientation_disagreement_detected(self):
        # scores implica player_1 vincitore ma event_winner dice "Second Player":
        # se sistematico su tutto il dataset segnala orientamento invertito.
        records = [
            FixtureScoreRecord(
                match_id=1,
                scores=_api_tennis_scores(("6", "4"), ("6", "3")),
                event_game_result=None,
                event_winner="Second Player",
            ),
        ]
        report = _summarize_records(records)

        self.assertEqual(report["orientation_check"]["disagree_with_event_winner"], 1)
        self.assertEqual(report["orientation_check"]["agreement_pct"], 0.0)

    def test_retirement_excluded_but_counted_as_suspected(self):
        records = [
            FixtureScoreRecord(
                match_id=1,
                scores=_api_tennis_scores(("6", "4"), ("3", "2")),
                event_game_result=None,
                event_winner="First Player",
            ),
        ]
        report = _summarize_records(records)

        self.assertEqual(report["suspected_retirement_or_anomalous"], 1)
        self.assertEqual(report["valid_for_training"], 0)


if __name__ == "__main__":
    unittest.main()





