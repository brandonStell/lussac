import copy
import os
from lussac.core import LussacPipeline, MonoSortingData
from lussac.modules import ExportToPhy


def test_default_params(mono_sorting_data: MonoSortingData) -> None:
	module = ExportToPhy("test_etp_params", mono_sorting_data, "all")
	assert isinstance(module.default_params, dict)


def test_export_multiple_sortings(pipeline: LussacPipeline) -> None:
	folder = "tests/datasets/cerebellar_cortex/lussac/output_phy"
	params = {
		'sortings': ['ks2_best', 'ms3_cs'],
		'path': folder,
		'wvf_extraction': {
			'ms_before': 1.0,
			'ms_after': 2.0,
			'max_spikes_per_unit': 10,
			'chunk_duration': '1s',
			'n_jobs': 6
		},
		'export_params': {
			'compute_pc_features': False,
			'compute_amplitudes': False,
			'sparsity': {
				'method': "radius",
				'radius_um': 50
			},
			'template_mode': "average",
			'copy_binary': False,
			'chunk_duration': '1s',
			'n_jobs': 6
		}
	}

	pipeline._run_mono_sorting_module(ExportToPhy, "export_to_phy", "all", params)

	assert os.path.exists(f"{folder}/ks2_best/spike_times.npy")
	assert os.path.exists(f"{folder}/ms3_cs/spike_times.npy")
	assert not os.path.exists(f"{folder}/ks2_cs/spike_times.npy")


def test_format_output_path(mono_sorting_data: MonoSortingData) -> None:
	module = ExportToPhy("test_etp_format_path", mono_sorting_data, "all")
	assert module._format_output_path("test") == "test/ms3_best"

	module = copy.deepcopy(module)
	module.data.data.sortings = {'ms3_best': module.sorting}
	assert module._format_output_path("test") == "test"
