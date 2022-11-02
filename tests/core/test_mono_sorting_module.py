from pathlib import Path
import pytest
import numpy as np
from lussac.core.lussac_data import MonoSortingData
from lussac.core.module import MonoSortingModule


def test_recording(mono_sorting_module: MonoSortingModule) -> None:
	assert mono_sorting_module.recording == mono_sorting_module.data.recording


def test_sorting(mono_sorting_module: MonoSortingModule) -> None:
	assert mono_sorting_module.sorting == mono_sorting_module.data.sorting


def test_logs_folder(mono_sorting_module: MonoSortingModule) -> None:
	assert mono_sorting_module.logs_folder == f"{mono_sorting_module.data.logs_folder}/test_mono_sorting_module/all/ms3_best"


def test_extract_waveforms(mono_sorting_module: MonoSortingModule) -> None:
	wvf_extractor_1 = mono_sorting_module.extract_waveforms(ms_before=1.5, ms_after=2.0, max_spikes_per_unit=10, overwrite=True)
	wvf_extractor_2 = mono_sorting_module.extract_waveforms(sub_folder="aze", ms_before=1.5, ms_after=2.0, max_spikes_per_unit=10, overwrite=True)

	assert wvf_extractor_1 is not None
	assert wvf_extractor_2 is not None
	assert Path(f"{mono_sorting_module.data.tmp_folder}/test_mono_sorting_module/all/ms3_best/wvf_extractor/waveforms").is_dir()
	assert Path(f"{mono_sorting_module.data.tmp_folder}/test_mono_sorting_module/all/ms3_best/aze/wvf_extractor/waveforms").is_dir()


def test_get_templates(mono_sorting_module: MonoSortingModule) -> None:
	ms_before, ms_after = (2.0, 2.0)
	templates, wvf_extractor, _ = mono_sorting_module.get_templates({'ms_before': ms_before, 'ms_after': ms_after}, filter_band=[300, 6000], return_extractor=True)

	n_units = mono_sorting_module.sorting.get_num_units()
	n_samples = int(round((ms_before + ms_after) * mono_sorting_module.sampling_f * 1e-3))
	n_channels = mono_sorting_module.recording.get_num_channels()

	assert templates is not None
	assert templates.shape == (n_units, n_samples, n_channels)
	assert np.all(wvf_extractor.unit_ids == mono_sorting_module.sorting.unit_ids)


@pytest.fixture(scope="function")
def mono_sorting_module(mono_sorting_data: MonoSortingData) -> MonoSortingModule:
	return TestMonoSortingModule(mono_sorting_data)


class TestMonoSortingModule(MonoSortingModule):
	"""
	This is just a test class.
	"""

	__test__ = False

	def __init__(self, data: MonoSortingData):
		super().__init__("test_mono_sorting_module", data, "all")

	def run(self, params: dict):
		pass
