from itertools import product
import pytest
from application.archive_folders import ArchiveFolders


@pytest.mark.parametrize('tags,score,favorite',product([False,True],repeat=3))
def test_folder_policy_omits_disabled_dimensions_and_preserves_tag_branches(tags,score,favorite):
    policy=ArchiveFolders(tags,score,favorite)
    prefix=(('未评分',) if score else ())+(('未收藏',) if favorite else ())
    expected=(prefix+('父','子'),prefix+('独立',)) if tags else (prefix,)
    assert policy.directories(None,False,[('父','子'),('独立',)])==expected
    assert ArchiveFolders.from_dict(policy.to_dict())==policy


@pytest.mark.parametrize('value',[None,[],{},dict(tags=True,score=True,favorite=1),
                                  dict(tags=True,score=True,favorite=False,unknown=True)])
def test_bad_configuration_is_rejected(value):
    with pytest.raises(ValueError):
        ArchiveFolders.from_dict(value)
