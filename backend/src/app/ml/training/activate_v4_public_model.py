"""Fase 6 — Registra e attiva v4 nel registro pubblico ML-07.

Passo separato da ``publish_v4_model.py`` (che produce solo gli artefatti
.pkl/metriche): questo script registra ``v4/voting_ensemble`` come candidato nel
registro ``PublicModelRegistryEntry`` e lo attiva, cosi' il bot Telegram e la
pubblicazione live iniziano a usarlo (``_resolve_active_public_model`` legge
sempre il registro, mai un default statico).

Il modello precedentemente attivo viene automaticamente marcato ``retired``
(non cancellato: resta disponibile per un eventuale rollback via endpoint
``/public-model-registry/rollback`` o funzione ``rollback_active_registry_entry``).

Uso (da repo root, richiede DB raggiungibile)::

    python -m backend.src.app.ml.training.activate_v4_public_model --motivation "..."
    python -m backend.src.app.ml.training.activate_v4_public_model --dry-run   # solo registra, non attiva
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.src.app.db.session import SessionLocal  # noqa: E402
from backend.src.app.services.public_model_registry import (  # noqa: E402
    activate_registry_entry,
    entry_to_read,
    get_active_registry_entry,
    load_holdout_approval_metrics,
    register_candidate,
)
from backend.src.entity.public_model_registry import PublicModelRegistryEntry  # noqa: E402

logger = logging.getLogger(__name__)

MODEL_VERSION = "v4"
MODEL_NAME = "voting_ensemble"

DEFAULT_MOTIVATION = (
    "Promozione v4 (soft-voting ensemble: logistic_regression + xgboost + "
    "hist_gradient_boosting). Grid search Fasi 1-2, voting Fase 3 (batte stacking "
    "Fase 4 e tutti i modelli singoli su ROC AUC/ROI holdout), validato con "
    "walk-forward multi-finestra Fase 5 (10 fold, ROC AUC 0.7750 vs 0.7749 RF / "
    "0.7727 LR) e Fase 5.2 con soglia di maturita' storica >=3 anni (7 fold, "
    "ROC AUC 0.7848, ROI value-bet cumulativo -1.61%, il migliore multi-periodo "
    "di tutto il progetto v1-v4)."
)


def activate_v4(
    *,
    motivation: str = DEFAULT_MOTIVATION,
    dry_run: bool = False,
    db: Any = None,
) -> dict:
    """Registra (ed eventualmente attiva) v4/voting_ensemble nel registro ML-07.

    ``db`` e' opzionale per testabilita': se ``None`` (uso CLI normale) apre una
    sessione reale con ``SessionLocal()``; nei test si puo' passare una sessione
    gia' aperta (es. fixture ``db_session``) senza duplicare la logica.
    """
    if db is not None:
        return _activate_v4_with_session(db, motivation=motivation, dry_run=dry_run)
    with SessionLocal() as session:
        return _activate_v4_with_session(session, motivation=motivation, dry_run=dry_run)


def _find_existing_candidate(db: Any) -> PublicModelRegistryEntry | None:
    """Trova un candidato v4/voting_ensemble gia' registrato (idempotenza: uno
    script rieseguito, es. dopo un --dry-run, non deve fallire su una entry
    'candidate' gia' aperta ne' crearne una duplicata)."""
    from sqlalchemy import select

    return db.scalar(
        select(PublicModelRegistryEntry)
        .where(
            PublicModelRegistryEntry.model_version == MODEL_VERSION,
            PublicModelRegistryEntry.model_name == MODEL_NAME,
            PublicModelRegistryEntry.status == "candidate",
        )
        .order_by(PublicModelRegistryEntry.id.desc())
        .limit(1)
    )


def _activate_v4_with_session(db: Any, *, motivation: str, dry_run: bool) -> dict:
    current_active = get_active_registry_entry(db)

    existing_candidate = _find_existing_candidate(db)
    if existing_candidate is not None:
        candidate = existing_candidate
        logger.info(
            "Riuso candidato gia' registrato id=%s %s/%s (non ne creo uno nuovo)",
            candidate.id,
            MODEL_VERSION,
            MODEL_NAME,
        )
    else:
        approval_metrics = load_holdout_approval_metrics(MODEL_VERSION, MODEL_NAME)
        candidate = register_candidate(
            db,
            model_version=MODEL_VERSION,
            model_name=MODEL_NAME,
            motivation=motivation,
            approval_metrics=approval_metrics,
            created_by="publish_v4_script",
        )
        logger.info("Candidato registrato id=%s %s/%s", candidate.id, MODEL_VERSION, MODEL_NAME)

    if dry_run:
        return {
            "action": "registered_only",
            "candidate": entry_to_read(candidate).model_dump(mode="json"),
            "previous_active": (
                entry_to_read(current_active).model_dump(mode="json")
                if current_active is not None
                else None
            ),
        }

    activated, previous = activate_registry_entry(
        db,
        candidate.id,
        motivation=motivation,
        created_by="publish_v4_script",
    )
    logger.info(
        "Modello pubblico attivo: %s/%s (id=%s, supersedes id=%s)",
        activated.model_version,
        activated.model_name,
        activated.id,
        previous.id if previous else None,
    )
    return {
        "action": "activated",
        "active": entry_to_read(activated).model_dump(mode="json"),
        "previous_active": entry_to_read(previous).model_dump(mode="json") if previous else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Registra e attiva v4/voting_ensemble nel registro pubblico ML-07."
    )
    parser.add_argument("--motivation", default=DEFAULT_MOTIVATION)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Registra solo come candidato, non attiva (nessun cambio per bot/utenti).",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    result = activate_v4(motivation=args.motivation, dry_run=args.dry_run)
    if result["action"] == "registered_only":
        print(f"Candidato registrato (non attivato): id={result['candidate']['id']}")
    else:
        print(
            f"Modello pubblico ATTIVO: {result['active']['model_version']}/{result['active']['model_name']} "
            f"(id={result['active']['id']})"
        )
        if result["previous_active"]:
            print(
                f"Precedente modello attivo ora 'retired': "
                f"{result['previous_active']['model_version']}/{result['previous_active']['model_name']} "
                f"(id={result['previous_active']['id']})"
            )


if __name__ == "__main__":
    main()





