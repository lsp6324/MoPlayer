from itertools import product
import pytest
from application.archive_folders import ArchiveFolders


@pytest.mark.parametrize('tags,score,favorite',product([False,True],repeat=3))
def test_folder_policy_omits_disabled_dimensions_and_preserves_tag_branches(tags,score,favorite):
    policy=ArchiveFolders(tags,score,favorite)
    prefix=(('未收藏',) if favorite else ())+(('未评分',) if score else ())
    expected=(prefix+('父','子'),prefix+('独立',)) if tags else (prefix,)
    assert policy.directories(None,False,[('父','子'),('独立',)])==expected
    assert ArchiveFolders.from_dict(policy.to_dict())==policy


@pytest.mark.parametrize('value',[None,[],{},dict(tags=True,score=True,favorite=1),
                                  dict(tags=True,score=True,favorite=False,unknown=True)])
def test_bad_configuration_is_rejected(value):
    with pytest.raises(ValueError):
        ArchiveFolders.from_dict(value)


def test_old_preferences_use_new_order_but_unversioned_frozen_jobs_keep_old_order():
    old = dict(tags=True, score=True, favorite=True)
    assert ArchiveFolders.from_dict(old).directories(8, True, [('风景',)]) == (('已收藏', '8分', '风景'),)
    frozen = ArchiveFolders.from_dict(old, legacy_job=True)
    assert frozen.directories(8, True, [('风景',)]) == (('8分', '已收藏', '风景'),)
    assert ArchiveFolders.from_dict(frozen.to_dict()) == frozen
    current = ArchiveFolders(favorite=True)
    assert ArchiveFolders.from_dict(current.to_dict(), legacy_job=True) == current
