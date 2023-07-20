import os

import numba
import pytest
import numpy as np
import probeinterface as pi
from lussac.core import LussacData
import spikeinterface.core as si


def test_format_params() -> None:
	with pytest.raises(Exception):
		LussacData._format_params({0: {}})
	with pytest.raises(Exception):
		LussacData._format_params({'aze': 1})
	with pytest.raises(Exception):
		LussacData._format_params({'aze': {2: {}}})
	with pytest.raises(Exception):
		LussacData._format_params({'aze': {'aze': 3}})

	params = {
		'module': {
			"cat1": {'a': 1},
			"cat2;cat3": {'b': 2}
		}
	}
	formatted_params = LussacData._format_params(params)
	assert 'cat2' in formatted_params['module']
	assert 'cat3' in formatted_params['module']
	assert 'cat2;cat3' not in formatted_params['module']
	formatted_params['module']['cat2']['b'] = 3
	assert formatted_params['module']['cat1']['a'] == 1
	assert formatted_params['module']['cat2']['b'] == 3
	assert formatted_params['module']['cat3']['b'] == 2


def test_sanity_check() -> None:
	recording = si.NumpyRecording(np.zeros((30000, 4), dtype=np.int16), sampling_frequency=30000)
	probe = pi.generator.generate_tetrode()
	probe.set_device_channel_indices([0, 1, 2, 3])
	recording = recording.set_probe(probe)

	sortings = {
		'correct': si.NumpySorting.from_dict({0: np.array([0, 8, 7188, 29999]), 1: np.array([87, 9368, 21845])}, sampling_frequency=30000),
		'wrong_sf': si.NumpySorting.from_dict({0: np.array([0, 8, 7188, 29999]), 1: np.array([87, 9368, 21845])}, sampling_frequency=10000),
		'wrong_name': si.NumpySorting.from_dict({0: np.array([0, 8, 7188, 29999]), 1: np.array([87, 9368, 21845])}, sampling_frequency=30000),
		'negative_st': si.NumpySorting.from_dict({0: np.array([0, 8, 7188, 29999]), 1: np.array([-87, 9368, 21845])}, sampling_frequency=30000)
	}
	for name, sorting in sortings.items():
		sorting.annotate(name=name if name != "wrong_name" else "uncorrect_name")

	lussac_default_params = {'lussac': {'pipeline': {}, 'tmp_folder': "tests/tmp", 'logs_folder': "tests/tmp/logs"}}
	LussacData(recording, {'correct': sortings['correct']}, lussac_default_params)

	for name, sorting in sortings.items():
		if name == "correct":
			continue

		with pytest.raises(AssertionError):
			LussacData(recording, {'correct': sortings['correct'], name: sorting}, lussac_default_params)


def test_tmp_folder(data: LussacData) -> None:
	assert os.path.exists(data.tmp_folder)
	assert os.path.isdir(data.tmp_folder)


def test_logs_folder(data: LussacData) -> None:
	assert os.path.exists(data.logs_folder)
	assert os.path.isdir(data.logs_folder)


def test_sampling_f(data: LussacData) -> None:
	assert data.sampling_f == 30000


def test_num_sortings(data: LussacData) -> None:
	assert data.num_sortings == 7


def test_load_sortings(data: LussacData) -> None:
	with pytest.raises(FileNotFoundError):
		data._load_sortings({'aze': "./qdjsgpfdhsig.json"})

	# TODO: Generate 'provenance.json' file in tmp folder and test loading from it.


def test_create_from_params(data: LussacData) -> None:
	assert isinstance(data, LussacData)

	assert numba.get_num_threads() == si.get_global_job_kwargs()['n_jobs']
	assert numba.get_num_threads() == 2  # Max number of threads for GitHub Actions.


def test_logs(data: LussacData) -> None:
	logs_file = data.logs_folder / "lussac.logs"

	assert logs_file.exists() and logs_file.is_file()

	# TODO: Seems to not log when in pytest mode.
	# with open(logs_file, 'r') as file:
	# 	assert len(file.read()) > 2