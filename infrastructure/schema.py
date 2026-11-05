"""Versioned additive migrations for the existing portable library."""


def migrate(connection):
    version = connection.execute('PRAGMA user_version').fetchone()[0]
    if version > 1:
        raise RuntimeError('资料库版本较新，请使用更新版本的 MoPlayer。')
    if version < 1:
        connection.execute('BEGIN IMMEDIATE')
        try:
            connection.execute('CREATE TABLE cleanup_jobs(id TEXT PRIMARY KEY,video TEXT NOT NULL,path TEXT NOT NULL COLLATE NOCASE,identity TEXT NOT NULL,size INTEGER NOT NULL,mtime INTEGER NOT NULL,state TEXT NOT NULL,error TEXT,updated REAL NOT NULL)')
            connection.execute('CREATE INDEX cleanup_path ON cleanup_jobs(path,identity,state)')
            connection.execute('PRAGMA user_version=1')
            connection.commit()
        except Exception:
            connection.rollback()
            raise
