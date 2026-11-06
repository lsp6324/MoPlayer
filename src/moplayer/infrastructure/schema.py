"""Versioned additive migrations for the existing portable library."""


def migrate(connection):
    version = connection.execute('PRAGMA user_version').fetchone()[0]
    if version > 3:
        raise RuntimeError('资料库版本较新，请使用更新版本的 MoPlayer。')
    if version < 3:
        connection.execute('BEGIN IMMEDIATE')
        try:
            if version < 1:
                connection.execute('CREATE TABLE cleanup_jobs(id TEXT PRIMARY KEY,video TEXT NOT NULL,path TEXT NOT NULL COLLATE NOCASE,identity TEXT NOT NULL,size INTEGER NOT NULL,mtime INTEGER NOT NULL,state TEXT NOT NULL,error TEXT,updated REAL NOT NULL)')
                connection.execute('CREATE INDEX cleanup_path ON cleanup_jobs(path,identity,state)')
            if version < 2:
                columns = {row[1] for row in connection.execute('PRAGMA table_info(videos)')}
                if 'archived_at' not in columns:
                    connection.execute('ALTER TABLE videos ADD COLUMN archived_at REAL')
                connection.execute('CREATE INDEX IF NOT EXISTS catalog_archived_at ON videos(archived,archived_at)')
                connection.execute('PRAGMA user_version=2')
            columns = {row[1] for row in connection.execute('PRAGMA table_info(videos)')}
            if 'in_library' not in columns:
                connection.execute('ALTER TABLE videos ADD COLUMN in_library INTEGER NOT NULL DEFAULT 0')
            if 'library_added_at' not in columns:
                connection.execute('ALTER TABLE videos ADD COLUMN library_added_at REAL')
            # Old marked files belong to the library even when never organized.
            # Only existing archive dates are known; never invent migration dates.
            marked = "({prefix}archived=1 OR {prefix}score IS NOT NULL OR {prefix}star=1 OR CASE WHEN json_valid({prefix}tags) THEN json_array_length({prefix}tags)>0 ELSE 0 END)"
            connection.execute('UPDATE videos SET library_added_at=CASE WHEN in_library=0 AND archived=1 THEN archived_at ELSE library_added_at END,in_library=1 WHERE ' + marked.format(prefix=''))
            connection.execute('CREATE INDEX IF NOT EXISTS catalog_library_added_at ON videos(in_library,library_added_at)')
            # A committed marker and first enrollment form one transaction,
            # including writes made by durable archive/tag recovery. Clearing
            # markers never drops membership or replaces an old unknown date.
            new_marked = marked.format(prefix='NEW.')
            for event, suffix in (('INSERT', 'insert'), ('UPDATE OF score,star,tags,archived', 'update')):
                connection.execute(f'''CREATE TRIGGER IF NOT EXISTS library_enroll_{suffix}
                    AFTER {event} ON videos WHEN NEW.in_library=0 AND {new_marked}
                    BEGIN
                        UPDATE videos SET in_library=1,
                            library_added_at=COALESCE(NEW.library_added_at,(julianday('now')-2440587.5)*86400.0)
                        WHERE id=NEW.id;
                    END''')
            connection.execute('PRAGMA user_version=3')
            connection.commit()
        except Exception:
            connection.rollback()
            raise
