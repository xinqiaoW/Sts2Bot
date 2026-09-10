from damage_model.worker import asset_loading_failure


def test_asset_loading_crash_is_request_and_stage_scoped():
    text = '''[CombatSolver/Unattended] STAGE run_id=current stage=start_run elapsed_ms=1
at: _ref (core/variant/array.cpp:63)
Fatal error. 0xC0000005
AssetLoadingSession.CheckLoadingStatus()
AssetLoadingSession.Process()
NAssetLoader._Process(double)'''
    assert asset_loading_failure(text, 'current')
    assert not asset_loading_failure(text, 'previous')
    assert not asset_loading_failure(text.replace('stage=start_run', 'stage=wait_combat_end'), 'current')
    assert not asset_loading_failure(text.replace('0xC0000005', 'other'), 'current')
    assert not asset_loading_failure(text + '\n[CombatSolver/Unattended] STAGE run_id=current stage=wait_combat_end ', 'current')
