"""Versioned additive migrations for the existing portable library."""


def migrate(connection):
    version = connection.execute('PRAGMA user_version').fetchone()[0]
    if version > 2:
        raise RuntimeError('资料库版本较新，请使用更新版本的 MoPlayer。')
    if version < 2:
        connection.execute('BEGIN IMMEDIATE')
        try:
            if version < 1:
                connection.execute('CREATE TABLE cleanup_jobs(id TEXT PRIMARY KEY,video TEXT NOT NULL,path TEXT NOT NULL COLLATE NOCASE,identity TEXT NOT NULL,size INTEGER NOT NULL,mtime INTEGER NOT NULL,state TEXT NOT NULL,error TEXT,updated REAL NOT NULL)')
                connection.execute('CREATE INDEX cleanup_path ON cleanup_jobs(path,identity,state)')
            columns = {row[1] for row in connection.execute('PRAGMA table_info(videos)')}
            if 'archived_at' not in columns:
                connection.execute('ALTER TABLE videos ADD COLUMN archived_at REAL')
            connection.execute('CREATE INDEX IF NOT EXISTS catalog_archived_at ON videos(archived,archived_at)')
            connection.execute('PRAGMA user_version=2')
            connection.commit()
        except Exception:
            connection.rollback()
            raise
