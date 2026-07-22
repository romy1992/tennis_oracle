"""Legacy CRUD repositories used by ``service.import_*``.

API/read paths should use ``app.services`` + ``Session`` from ``app.db.session``.
Session factory is shared via ``repository.base.repository_db`` → ``app.db.session``.
"""
