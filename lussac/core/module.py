from abc import ABC, abstractmethod
from dataclasses import dataclass
import os
import shutil
from typing import Any
import numpy as np
from lussac.core.lussac_data import MonoSortingData, MultiSortingsData
import lussac.utils as utils
import spikeinterface.core as si
import spikeinterface.preprocessing as spre
import spikeinterface.postprocessing as spost
import spikeinterface.qualitymetrics as sqm


@dataclass(slots=True)
class LussacModule(ABC):
	"""
	The abstract Module class.
	Every module used in Lussac must inherit from this class.

	Attributes:
		name		Module's name (i.e. the key in the pipeline dictionary).
		data 		Reference to the data object.
		category	What category is used for the module (i.e. the key in the dictionary).
		logs_folder	Path to the folder where to output the logs.
	"""

	name: str
	data: MonoSortingData | MultiSortingsData
	category: str

	@property
	def recording(self) -> si.BaseRecording:
		"""
		Returns the recording object.

		@return recording: BaseRecording
			The recording object.
		"""

		return self.data.recording

	@property
	def sampling_f(self) -> float:
		"""
		Returns the sampling frequency of the recording (in Hz).

		@return sampling_f: float
			The sampling frequency (in Hz).
		"""

		return self.recording.sampling_frequency

	@abstractmethod
	def run(self, params: dict[str, Any]) -> si.BaseSorting | dict[str, si.BaseSorting]:
		"""
		Executes the module and returns the result (either a sorting of a dict of sortings).

		@param params: dict
			The parameters for the module.
		@return result: si.BaseSorting | dict[str, si.BaseSorting]
			The result of the module.
		"""
		...

	@property
	@abstractmethod
	def default_params(self) -> dict[str, Any]:
		"""
		Returns the default parameters of the module.

		@return default_params: dict[str, Any]
			The default parameters of the module.
		"""
		...

	def update_params(self, params: dict[str, Any]) -> dict[str, Any]:
		"""
		Updates the parameters with the default parameters (if there is a conflict, the given parameters are taken).
		Need to update recursively because the parameters are usually a nested dictionary.
		This is done by flattening then unflattening the dictionaries.

		@param params: dict[str, Any]
			The parameters to update.
		@return updated_params: dict[str, Any]
			The parameters updated with the module's default parameters.
		"""
		sep = ':'

		flattened_params = utils.flatten_dict(params, sep=sep)
		flattened_default = utils.flatten_dict(self.default_params, sep=sep)
		updated_params = flattened_default | flattened_params

		return utils.unflatten_dict(updated_params, sep=sep)


@dataclass(slots=True)
class MonoSortingModule(LussacModule):
	"""
	The abstract mono-sorting module class.
	This is for modules that don't work on multiple sortings at once.

	Attributes:
		name		Module's name (i.e. the key in the pipeline dictionary).
		data		Reference to the mono-sorting data object.
		logs_folder	Path to the folder where to output the logs.
	"""

	data: MonoSortingData

	def __del__(self) -> None:
		"""
		When the module is garbage collected, remove the temporary folder.
		"""

		if os.path.exists(f"{self.data.tmp_folder}/{self.name}"):
			shutil.rmtree(f"{self.data.tmp_folder}/{self.name}")

	@property
	def sorting(self) -> si.BaseSorting:
		"""
		Returns the sorting object.

		@return sorting: BaseSorting
			The sorting object.
		"""

		return self.data.sorting

	@property
	def logs_folder(self) -> str:
		"""
		Returns the logs directory for this module.

		@return logs_folder: str
			Path to the logs directory.
		"""

		logs_folder = f"{self.data.logs_folder}/{self.name}/{self.category}/{self.data.name}"
		if not os.path.exists(logs_folder):
			os.makedirs(logs_folder)

		return logs_folder

	@abstractmethod
	def run(self, params: dict[str, Any]) -> si.BaseSorting:
		...

	def extract_waveforms(self, sorting: si.BaseSorting | None = None, sub_folder: str | None = None, filter: dict[str, Any] | None = None, **params) -> si.WaveformExtractor:
		"""
		Creates the WaveformExtractor object and returns it.

		@param sorting: BaseSorting | None
			The sorting for the WaveformExtractor.
			If None, will take the sorting from the data object.
		@param sub_folder: str | None:
			The sub-folder where to save the waveforms.
		@param params
			The parameters for the waveform extractor.
		@param filter: dict | None
			The filter to apply to the recording.
		@return wvf_extractor: WaveformExtractor
			The waveform extractor object.
		"""
		if sub_folder is None:
			sub_folder = "wvf_extractor"

		folder_path = f"{self.data.tmp_folder}/{self.name}/{self.category}/{self.data.name}/{sub_folder}"

		if 'chunk_duration' not in params:
			params['chunk_duration'] = '1s'
		if 'n_jobs' not in params:
			params['n_jobs'] = 6

		recording = self.recording
		if filter is not None:
			recording = spre.filter(recording, **filter)

		sorting = self.sorting if sorting is None else sorting
		return si.extract_waveforms(recording, sorting, folder_path, allow_unfiltered=True, **params)

	def get_templates(self, params: dict, filter_band: tuple[float, float] | list[float, float] | np.ndarray | None = None, margin: float = 3.0,
					  sub_folder: str = "templates", return_extractor: bool = False) -> np.ndarray | tuple[np.ndarray, si.WaveformExtractor, int]:
		"""
		Extract the templates for all the units.
		If filter_band is not None, will also filter them using a Gaussian filter.

		@param params: dict
			The parameters for the waveform extraction.
		@param filter_band: Iterable[float, float] | None
			If not none, the highpass and lowpass cutoff frequencies (in Hz).
		@param margin: float
			The margin (in ms) to extract (useful for filtering).
		@param sub_folder: str
			The sub-folder used for the waveform extractor.
		@param return_extractor: bool
			If true, will also return the waveform extractor and margin (in samples).
		@return templates: np.ndarray (n_units, n_samples, n_channels)
			The extracted templates
		@return wvf_extractor: si.WaveformExtractor
			The Waveform Extractor of unfiltered waveforms.
			Only if return_extractor is True.
		@return margin: int
			The margin (in samples) that were used for the filtering.
			Only if return_extractor is True.
		"""

		params = params.copy()
		params['ms_before'] += margin
		params['ms_after'] += margin
		wvf_extractor = self.extract_waveforms(sub_folder=sub_folder, **params)
		templates = wvf_extractor.get_all_templates()

		if filter_band is not None:
			templates = utils.filter(templates, filter_band, axis=1)

		margin = int(round(margin * self.recording.sampling_frequency * 1e-3))

		if return_extractor:
			return templates[:, margin:-margin], wvf_extractor, margin
		else:
			return templates[:, margin:-margin]

	def get_units_attribute(self, attribute: str, params: dict) -> dict:
		"""
		Gets the attribute for all the units.

		@param attribute: str
			The attribute name.
			- firing_rate (in Hz)
			- contamination (between 0 and 1)
			- amplitude (unit depends on the wvf extractor 'return_scaled' parameter)
			- amplitude_std (unit depends on parameters 'return_scaled')
		@param params: dict
			The parameters to get the attribute.
			- 'filter': parameters to filter the recording.
			- 'wvf_extraction': parameters to extract the waveforms.
			- others: parameters for how to get the attribute.
		@return attribute: np.ndarray
			The attribute for all the units.
		"""
		recording = self.data.recording
		sorting = self.sorting
		if 'filter' in params:
			recording = spre.filter(recording, **params['filter'])

		wvf_extractor = self.extract_waveforms(sub_folder=attribute, **params['wvf_extraction']) if 'wvf_extraction' in params \
						else si.WaveformExtractor(recording, sorting, allow_unfiltered=True)

		# TODO: Probably a better way to handle 'params' than manually setting each parameter individually.
		match attribute:
			case "firing_rate":  # Returns the firing rate of each unit (in Hz).
				n_spikes = {unit_id: len(sorting.get_unit_spike_train(unit_id)) for unit_id in sorting.unit_ids}
				firing_rates = {unit_id: n_spike * sorting.get_sampling_frequency() / recording.get_num_frames() for unit_id, n_spike in n_spikes.items()}
				return firing_rates

			case "contamination":  # Returns the estimated contamination of each unit.
				censored_period, refractory_period = params['refractory_period']
				contamination = sqm.compute_refrac_period_violations(wvf_extractor, refractory_period, censored_period)[1]
				return contamination

			case "amplitude":  # Returns the amplitude of each unit on its best channel (unit depends on the wvf extractor 'return_scaled' parameter).
				peak_sign = params['peak_sign'] if 'peak_sign' in params else "both"
				mode = params['mode'] if 'mode' in params else "extremum"
				amplitudes = si.template_tools.get_template_extremum_amplitude(wvf_extractor, peak_sign, mode)
				return amplitudes

			case "SNR":  # Returns the signal-to-noise ratio of each unit on its best channel.
				peak_sign = params['peak_sign'] if 'peak_sign' in params else "both"
				peak_mode = params['peak_mode'] if 'peak_mode' in params else "extremum"
				SNRs = sqm.compute_snrs(wvf_extractor, peak_sign, peak_mode)
				return SNRs

			case "amplitude_std":  # Returns the standard deviation of the amplitude of spikes.
				peak_sign = params['peak_sign'] if 'peak_sign' in params else "both"
				return_scaled = params['return_scaled'] if 'return_scaled' in params else True
				chunk_duration = params['chunk_duration'] if 'chunk_duration' in params else '1s'
				n_jobs = params['n_jobs'] if 'n_jobs' in params else 6
				amplitudes = spost.compute_spike_amplitudes(wvf_extractor, peak_sign=peak_sign, return_scaled=return_scaled, outputs='by_unit', chunk_duration=chunk_duration, n_jobs=n_jobs)[0]
				std_amplitudes = {unit_id: np.std(amp) for unit_id, amp in amplitudes.items()}
				return std_amplitudes

			case "ISI_portion":  # Returns the portion of consecutive spikes that are between a certain range (in ms).
				low, high = np.array(params['range']) * recording.sampling_frequency * 1e-3
				diff = {unit_id: np.diff(sorting.get_unit_spike_train(unit_id)) for unit_id in sorting.unit_ids}
				ISI_portion = {unit_id: np.sum((low < d) & (d < high)) / len(d) for unit_id, d in diff.items()}
				return ISI_portion

			case _:
				raise ValueError(f"Unknown attribute: {attribute}")

	def get_units_attribute_arr(self, attribute: str, params: dict) -> np.array:
		"""
		See MonoSortingModule.get_units_attribute.
		Returns the same value but as a numpy array rather than a dict.
		"""

		return np.array(list(self.get_units_attribute(attribute, params).values()))


@dataclass(slots=True)
class MultiSortingsModule(LussacModule):
	"""
	The abstract multi-sorting module class.
	This is for modules that work on multiple sortings at once.

	Attributes:
		name		Module's name (i.e. the key in the pipeline dictionary).
		data		Reference to Lussac data object.
		logs_folder	Path to the folder where to output the logs.
	"""

	data: MultiSortingsData

	@property
	def sortings(self) -> dict[str, si.BaseSorting]:
		"""
		Returns the sorting objects.

		@return sortings: dict[str, BaseSorting]
			The sorting objects.
		"""

		return self.data.sortings

	@property
	def logs_folder(self) -> str:
		"""
		Returns the logs directory for this module.

		@return logs_folder: str
			Path to the logs directory.
		"""

		logs_folder = f"{self.data.logs_folder}/{self.name}/{self.category}"
		if not os.path.exists(logs_folder):
			os.makedirs(logs_folder)

		return logs_folder

	@abstractmethod
	def run(self, params: dict[str, Any]) -> dict[str, si.BaseSorting]:
		...
