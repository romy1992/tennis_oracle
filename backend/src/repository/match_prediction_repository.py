from backend.src.entity.match_prediction import MatchPrediction
from backend.src.repository.base.crud_repository import CrudRepository


class MatchPredictionRepository(CrudRepository):

    def __init__(self):
        super().__init__(MatchPrediction)
