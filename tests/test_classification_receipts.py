"""Receipts describe committed changes, including archives with no folder layers."""
import pytest
from application.archive_folders import ArchiveFolders
from application.classification import Classification
from application.file_tasks import FileTasks
from core import Archiver, Store, identity
from infrastructure.library_repository import LibraryRepository
from tag_migration import TagMigration


@pytest.fixture
def media(tmp_path):
    store = Store(tmp_path/'data')
    repo = LibraryRepository(store)
    root = tmp_path/'归档库'
    archiver = Archiver(store, root, folders=ArchiveFolders(False, False, False))
    migration = TagMigration(store, archiver)
    queue, notices = [], []
    tasks = FileTasks(lambda work, done: queue.append((work, done)), lambda policy: None,
                      lambda bookmark: None, lambda: bool(repo.pending_tasks()))
    workflow = Classification(tasks, repo,
        lambda vid, score, tags, schema: migration.submit(vid, score, tags, schema, defer_cleanup=True),
        lambda vid, score, tags: archiver.submit(vid, score, tags, defer_cleanup=True),
        available=lambda: True, ensure_storage=lambda: True, refresh=lambda ids: None, notify=notices.append,
        favorite_folders=lambda: archiver.folders.favorite,
        submit_favorite=lambda vid, score, tags, value: archiver.submit(vid, score, tags, favorite=value, defer_cleanup=True),
        archive_locations=lambda vid: repo.archive_locations(vid, archiver.root))
    source = tmp_path/'电影.mp4'
    source.write_bytes(b'isolated archive receipt media' * 100)
    vid = store.register(source)

    def finish(operation):
        while queue:
            work, done = queue.pop(0)
            try:
                result = work()
            except Exception as error:
                done(None, error)
            else:
                done(result, None)
        assert operation.outcome.succeeded, operation.outcome.error
        return notices[-1] if notices else None

    def tags(value):
        schema = [dict(name=name, kind='major', parent=None) for name in value]
        return finish(workflow.apply_tags(vid, value, schema, prompt_score=False))

    yield workflow, repo, archiver, vid, notices, finish, tags
    store.db.close()


def test_first_archive_with_all_layers_disabled_reports_real_root_then_metadata_changes(media):
    workflow, repo, archive, vid, notices, finish, tags = media
    source_identity = identity(repo.resolve(vid))
    assert tags(['风景']).receipt_title == '已归档'
    assert notices[-1].receipt_detail == '归档库'
    assert repo.resolve(vid).parent == archive.root
    assert identity(repo.resolve(vid)) == source_identity
    directories = repo.media_directories(vid)
    assert tags(['旅行']).receipt_title == '标签已保存'
    assert notices[-1].receipt_detail == '电影.mp4'
    assert finish(workflow.rating(vid, 9)).receipt_title == '评分已更新'
    assert finish(workflow.favorite(vid, True)).receipt_title == '已收藏'
    assert finish(workflow.favorite(vid, False)).receipt_title == '已取消收藏'
    assert repo.media_directories(vid) == directories


def test_unchanged_values_do_not_publish_another_success_receipt(media):
    workflow, repo, archive, vid, notices, finish, tags = media
    tags(['风景'])
    notice = tags(['风景'])
    assert not notice.receipt_title and not notice.receipt_detail
    count = len(notices)
    assert workflow.rating(vid, repo.video(vid)['score']).outcome.succeeded
    assert workflow.favorite(vid, False).outcome.succeeded
    assert len(notices) == count


def test_unarchived_rating_and_favorite_are_metadata_receipts_without_archiving(media):
    workflow, repo, archive, vid, notices, finish, tags = media
    original = repo.resolve(vid)
    assert workflow.rating(vid, 7).outcome.succeeded
    assert notices[-1].receipt_title == '评分已更新'
    assert workflow.favorite(vid, True).outcome.succeeded
    assert notices[-1].receipt_title == '已收藏'
    assert repo.resolve(vid) == original and not repo.video(vid)['archived']


def test_directory_updates_take_precedence_only_when_active_directories_change(media):
    workflow, repo, archive, vid, notices, finish, tags = media
    archive.folders = ArchiveFolders(favorite=True)
    workflow.rating(vid, 8)
    assert tags(['风景']).receipt_detail == '未收藏 / 8分 / 风景'
    notice = finish(workflow.favorite(vid, True))
    assert notice.receipt_title == '目录已更新'
    assert notice.receipt_detail == '已收藏 / 8分 / 风景'
    notice = finish(workflow.rating(vid, 9))
    assert notice.receipt_title == '目录已更新'
    assert notice.receipt_detail == '已收藏 / 9分 / 风景'
    archive.folders = ArchiveFolders(True, False, False)
    tags(['风景'])  # Existing active paths are now brought under the new policy.
    notice = finish(workflow.rating(vid, 10))
    assert notice.receipt_title == '评分已更新'
    assert notice.receipt_detail == '电影.mp4'


def test_global_tag_schema_save_is_reported_even_when_current_files_do_not_move(media):
    workflow, repo, archive, vid, notices, finish, tags = media
    tags(['风景'])
    schema = [dict(name=name, kind='major', parent=None) for name in ('风景', '新标签')]
    notice = finish(workflow.apply_tags(vid, ['风景'], schema, prompt_score=False))
    assert notice.receipt_title == '标签已保存'
    assert notice.receipt_detail == '电影.mp4'


def test_failed_metadata_write_does_not_claim_success(media, monkeypatch):
    workflow, repo, archive, vid, notices, finish, tags = media
    def fail(*args):
        raise OSError('database unavailable')
    monkeypatch.setattr(repo, 'set_score', fail)
    result = workflow.rating(vid, 8)
    assert not result.outcome.succeeded and result.outcome.error
    assert not notices[-1].receipt_title
    assert repo.video(vid)['score'] is None
