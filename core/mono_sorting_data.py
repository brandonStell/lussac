from dataclasses import dataclass
import numpy as np
import spikeinterface.core as si
from core.lussac_data import LussacData


@dataclass(slots=True)
class MonoSortingData:
	"""
	Allows easy manipulation of the LussacData object when working on only one sorting.

	Attributes:
		data			The main data object for Lussac.
		active_sorting	Which sorting is currently being used?
	"""

	data: LussacData
	active_sorting: int = 0

	@property
	def sorting(self) -> si.BaseSorting:
		"""
		Returns the current active sorting.

		@return sorting: BaseSorting
		"""

		return self.data.sortings[self.active_sorting]

	@property
	def sampling_f(self) -> float:
		"""
		Returns the sampling frequency of the recording (in Hz).

		@return sampling_frequency: float
		"""

		return self.data.sampling_f

	def get_cluster_spike_train(self, cluster_id: int) -> np.ndarray:
		"""
		Returns the spike_train (i.e. an array containing all the spike timings)
		of a given cluster.

		@param cluster_id: int
			The cluster's ID of which to return the spike train.
		@return spike_train: np.ndarray
		"""

		return self.sorting.get_unit_spike_train(cluster_id)
