import math
import numpy as np
import numba
import scipy.stats
from .variables import Utils


def gaussian_histogram(events: np.ndarray, t_axis: np.ndarray, sigma: float, truncate: float = 5., margin_reflect: bool = False) -> np.ndarray:
	"""
	Computes a gaussian histogram for the given events.
	For each point in time, take all the nearby events and compute the sum of their gaussian kernel.

	@param events: np.ndarray
		The events to histogram.
	@param t_axis: np.ndarray
		The time axis of the histogram.
	@param sigma: float
		The standard deviation of the gaussian kernel (same unit as 't_axis').
	@param truncate: float
		Truncate the gaussian kernel at 'truncate' standard deviation.
	@param margin_reflect: bool
		If true, will reflect the events at the margins.
	@return histogram: np.ndarray
		The histogram of the events.
	"""

	events = np.sort(events).astype(np.float32)
	t_axis = t_axis.astype(np.float32)

	if margin_reflect:
		if np.min(events) >= t_axis[0]:
			events_low = 2*t_axis[0] - events[:np.searchsorted(events, t_axis[0] + truncate * sigma, side="right")][::-1]
		else:
			events_low = np.array([], dtype=np.float32)

		if np.max(events) <= t_axis[-1]:
			events_high = 2*t_axis[-1] - events[np.searchsorted(events, t_axis[-1] - truncate * sigma, side="left"):][::-1]
		else:
			events_high = np.array([], dtype=np.float32)

		events = np.concatenate((events_low, events, events_high))

	return _gaussian_kernel(events, t_axis, sigma, truncate)


@numba.jit((numba.float32[:], numba.float32[:], numba.float32, numba.float32), nopython=True, nogil=True, cache=True, parallel=True)
def _gaussian_kernel(events, t_axis, sigma, truncate):
	"""
	Numba function for gaussian_histogram.

	@param events: array[float32] (n_events)
		The ordered events timings.
	@param t_axis: array[float32] (n_timepoints)
		The time axis of the histogram.
	@param sigma: float32
		The standard deviation of the gaussian kernel (same unit as 't_axis').
	@param truncate: float32
		Truncate the gaussian kernel at 'truncate' standard deviation.
	@return histogram: array[float32] (n_timepoints)
		The gaussian histogram of the events.
	"""

	histogram = np.zeros(t_axis.shape, dtype=np.float32)

	start_j = 0
	for i in numba.prange(len(t_axis)):
		for e in events[start_j:]:
			if e < t_axis[i] - truncate * sigma:
				start_j += 1
				continue
			if e > t_axis[i] + truncate * sigma:
				break

			histogram[i] += np.exp(-0.5 * ((e - t_axis[i]) / sigma) ** 2)

	return histogram / (sigma * np.sqrt(2*np.pi))


def estimate_contamination(spike_train: np.ndarray, refractory_period: tuple[float, float]) -> float:
	"""
	Estimates the contamination of a spike train by looking at the number of refractory period violations.
	The spike train is assumed to have spikes coming from a neuron, and noisy spikes that are random and
	uncorrelated to the neuron. Under this assumption, we can estimate the contamination (i.e. the
	fraction of noisy spikes to the total number of spikes).

	@param spike_train: np.ndarray
		The unit's spike train.
	@param refractory_period: tuple[float, float]
		The censored and refractory period (t_c, t_r) used (in ms).
	@return estimated_contamination: float
		The estimated contamination between 0 and 1.
	"""

	t_c = refractory_period[0] * 1e-3 * Utils.sampling_frequency
	t_r = refractory_period[1] * 1e-3 * Utils.sampling_frequency
	n_v = compute_nb_violations(spike_train.astype(np.int64), t_r)

	N = len(spike_train)
	T = Utils.t_max
	D = 1 - n_v * (T - 2*N*t_c) / (N**2 * (t_r - t_c))
	contamination = 1.0 if D < 0 else 1 - math.sqrt(D)

	return contamination


def estimate_cross_contamination(spike_train1: np.ndarray, spike_train2: np.ndarray,
								 refractory_period: tuple[float, float], limit: float = 0.3) -> tuple[float, float]:
	"""
	Estimates the cross-contamination of the second spike train with the neuron of the first spike train.
	Also performs a statistical test to check if the cross-contamination is significantly higher than a given limit.

	@param spike_train1: np.ndarray
		The spike train of the first unit.
	@param spike_train2: np.ndarray
		The spike train of the second unit.
	@param refractory_period: tuple[float, float]
		The censored and refractory period (t_c, t_r) used (in ms).
	@param limit: float
		The higher limit of cross-contamination for the statistical test.
	@return (estimated_cross_cont, p_value): tuple[float, float]
		Returns the estimation of cross-contamination, as well as the p-value of the statistical test.
	"""
	spike_train1 = spike_train1.astype(np.int64)
	spike_train2 = spike_train2.astype(np.int64)

	N1 = len(spike_train1)
	N2 = len(spike_train2)
	C1 = estimate_contamination(spike_train1, refractory_period)

	t_c = refractory_period[0] * 1e-3 * Utils.sampling_frequency
	t_r = refractory_period[1] * 1e-3 * Utils.sampling_frequency
	n_violations = compute_nb_coincidence(spike_train1, spike_train2, t_r) - compute_nb_coincidence(spike_train1, spike_train2, t_c)

	estimation = 1 - ((n_violations * Utils.t_max) / (2*N1*N2 * t_r) - 1) / (C1 - 1) if C1 != 1.0 else -np.inf

	# n and p for the binomial law for the number of coincidence (under the hypothesis of cross-contamination = limit).
	n = N1 * N2 * ((1 - C1) * limit + C1)
	p = 2 * t_r / Utils.t_max
	if n*p < 30:
		p_value = 1 - scipy.stats.binom.cdf(n_violations, n, p)
	else:  # Approximate the binomial law by a normal law (binom.cdf fails for very high 'n').
		p_value = 1 - scipy.stats.norm.cdf(n_violations, n*p, math.sqrt(n*p*(1-p)))

	return estimation, p_value


@numba.jit((numba.float32, ), nopython=True, nogil=True, cache=True)
def _get_border_probabilities(max_time):
	"""
	Computes the integer borders, and the probability of 2 spikes distant by this border to be closer than max_time.

	@param max_time: float
		The maximum time between 2 spikes to be considered as a coincidence.
	@return border_low, border_high, p_low, p_high: tuple[int, int, float, float]
		The borders and their probabilities.
	"""

	border_high = math.ceil(max_time)
	border_low = math.floor(max_time)
	p_high = .5 * (max_time - border_high + 1) ** 2
	p_low  = .5 * (1 - (max_time - border_low)**2) + (max_time - border_low)

	if border_low == 0:
		p_low -= .5 * (-max_time + 1)**2

	return border_low, border_high, p_low, p_high


@numba.jit((numba.int64[:], numba.float32), nopython=True, nogil=True, cache=True)
def compute_nb_violations(spike_train, max_time):
	"""
	Computes the number of refractory period violations in a spike train.

	@param spike_train: array[int64] (n_spikes)
		The spike train to compute the number of violations for.
	@param max_time: float32
		The maximum time to consider for violations (in number of samples).
	@return n_violations: float
		The number of spike pairs that violate the refractory period.
	"""

	if max_time <= 0.0:
		return 0.0

	border_low, border_high, p_low, p_high = _get_border_probabilities(max_time)
	n_violations = 0
	n_violations_low = 0
	n_violations_high = 0

	for i in range(len(spike_train)-1):
		for j in range(i+1, len(spike_train)):
			diff = spike_train[j] - spike_train[i]

			if diff > border_high:
				break
			if diff == border_high:
				n_violations_high += 1
			elif diff == border_low:
				n_violations_low += 1
			else:
				n_violations += 1

	return n_violations + p_high*n_violations_high + p_low*n_violations_low


@numba.jit((numba.int64[:], numba.int64[:], numba.float32), nopython=True, nogil=True, cache=True)
def compute_nb_coincidence(spike_train1, spike_train2, max_time):
	"""
	Computes the number of coincident spikes between two spike trains.
	Spike timings are integers, so their real timing follows a uniform distribution between t - dt/2 and t + dt/2.
	Under the assumption that the uniform distributions from two spikes are independent, we can compute the probability
	of those two spikes being closer than the coincidence window:
	f(x) = 1/2 (x+1)² if -1 <= x <= 0
	f(x) = 1/2 (1-x²) + x if 0 <= x <= 1
	where x is the distance between max_time floor/ceil(max_time)

	@param spike_train1: array[int64] (n_spikes1)
		The spike train of the first unit.
	@param spike_train2: array[int64] (n_spikes2)
		The spike train of the second unit.
	@param max_time: float32
		The maximum time to consider for coincidence (in number samples).
	@return n_coincidence: float
		The number of coincident spikes.
	"""

	if max_time <= 0:
		return 0.0

	border_low, border_high, p_low, p_high = _get_border_probabilities(max_time)
	n_coincident = 0
	n_coincident_low = 0
	n_coincident_high = 0

	start_j = 0
	for i in range(len(spike_train1)):
		for j in range(start_j, len(spike_train2)):
			diff = spike_train1[i] - spike_train2[j]

			if diff > border_high:
				start_j += 1
				continue
			if diff < -border_high:
				break
			if abs(diff) == border_high:
				n_coincident_high += 1
			elif abs(diff) == border_low:
				n_coincident_low += 1
			else:
				n_coincident += 1

	return n_coincident + p_high*n_coincident_high + p_low*n_coincident_low


def compute_coincidence_matrix_from_vector(spike_vector1: np.ndarray, spike_vector2: np.ndarray, window: int):
	"""
	Computes the number of coincident spikes between two sortings (given their spike vector).

	@param spike_vector1: np.ndarray (n_spikes1)
		The spike vector of the first sorting.
	@param spike_vector2: np.ndarray (n_spikes2)
		The spike vector of the second sorting.
	@param window: int
		The coincidence window (in number of samples).
		Two spikes separated by exactly window are considered as coincident.
	@return coincidence_matrix: np.ndarray[int64] (n_units1, n_units2)
		The coincidence matrix containing the number of coincident spikes between each pair of units.
	"""

	return compute_coincidence_matrix(spike_vector1['sample_ind'], spike_vector1['unit_ind'],
									  spike_vector2['sample_ind'], spike_vector2['unit_ind'], window)


@numba.jit((numba.int64[:], numba.int64[:], numba.int64[:], numba.int64[:], numba.int32),
		   nopython=True, nogil=True, cache=True)
def compute_coincidence_matrix(spike_times1, spike_labels1, spike_times2, spike_labels2, max_time):
	"""
	Computes the number of coincident spikes between all units in two sortings.

	@param spike_times1: array[int64] (n_spikes1)
		All the spike timings of the first sorting.
	@param spike_labels1: array[int64] (n_spikes1)
		The unit labels of the first sorting (i.e. unit index of each spike).
	@param spike_times2: array[int64] (n_spikes2)
		All the spike timings of the second sorting.
	@param spike_labels2: array[int64] (n_spikes2)
		The unit labels of the second sorting (i.e. unit index of each spike).
	@param max_time: int32
		The maximum time difference between two spikes to be considered coincident.
		Two spikes spaced by exactly max_time are considered coincident.
	@return coincidence_matrix: array[int64] (n_units1, n_units2)
		The coincidence matrix containing the number of coincident spikes between each pair of units.
	"""

	n_units1 = np.max(spike_labels1) + 1
	n_units2 = np.max(spike_labels2) + 1
	coincidence_matrix = np.zeros((n_units1, n_units2), dtype=np.int64)

	start_j = 0
	for i in range(len(spike_times1)):
		for j in range(start_j, len(spike_times2)):
			diff = spike_times1[i] - spike_times2[j]

			if diff > max_time:
				start_j += 1
				continue
			if diff < -max_time:
				break

			coincidence_matrix[spike_labels1[i], spike_labels2[j]] += 1

	return coincidence_matrix


def compute_similarity_matrix(coincidence_matrix: np.ndarray, n_spikes1: np.ndarray, n_spikes2: np.ndarray, window: float = -.5):
	"""
	Computes the similarity matrix from the coincidence matrix.

	@param coincidence_matrix: array[int] (n_units1, n_units2)
		The coincidence matrix between the two sortings.
	@param n_spikes1: array[int] (n_units1)
		The number of spikes for each unit in the first sorting.
	@param n_spikes2: array[int] (n_units2)
		The number of spikes for each unit in the second sorting.
	@param window: int
		The window used for the coincidence matrix (to compute the corrected similarity matrix).
		Leave at -0.5 to compute the uncorrected similarity matrix.
	@return similarity_matrix: array[float] (n_units1, n_units2)
		The similarity matrix between the two sortings.
	"""
	assert coincidence_matrix.shape == (len(n_spikes1), len(n_spikes2))

	minimum_n_spikes = np.minimum(n_spikes1[:, None], n_spikes2)
	similarity_matrix = coincidence_matrix / minimum_n_spikes
	expected_matrix = (n_spikes1[:, None] * n_spikes2[None, :] * (2*window+1) / Utils.t_max) / minimum_n_spikes

	return (similarity_matrix - expected_matrix) / (1 - expected_matrix)


def filter(data: np.ndarray, band: tuple[float, float] | list[float, float] | np.ndarray, axis: int = -1) -> np.ndarray:
	"""
	Filters the data using a Gaussian bandpass filter.
	Since the Gaussian filter is a convolution with a Gaussian kernel, we can accelerate the filtering
	by using FFTs. The convolution in the time domain is a multiplication in the frequency domains.

	@param data: np.ndarray
		The data to filter.
	@param band: Iterable of two floats [highpass, lowpass]
		The highpass and lowpass frequencies (in Hz).
	@param axis: int
		The axis along which to filter the data.
	@return filtered_data: np.ndarray
		The filtered data.
	"""

	N = data.shape[axis]
	data_fft = np.fft.fft(data, axis=axis)
	gaussian_highpass = _create_fft_gaussian(N, band[0])
	gaussian_lowpass  = _create_fft_gaussian(N, band[1])

	broadcast = tuple(slice(None) if i == axis else None for i in range(data_fft.ndim))
	filtered_data_fft = data_fft * (gaussian_lowpass - gaussian_highpass)[broadcast]
	filtered_data = np.fft.ifft(filtered_data_fft, axis=axis).real

	return filtered_data


def _create_fft_gaussian(N: int, cutoff_freq: float) -> np.ndarray:
	"""
	Creates a Gaussian filter in the frequency domain for a given cutoff frequency.

	@param N: int
		The number of samples of the signal for the Fourier transform.
	@param cutoff_freq: float
		The cutoff frequency (in Hz).
	@return fft_gaussian: np.ndarray
		The Gaussian filter in the frequency domain.
	"""

	if cutoff_freq > Utils.sampling_frequency / 8:  # The Fourier transform of a Gaussian with a very low sigma isn't a Gaussian in the Fourier domain.
		sigma = Utils.sampling_frequency / (2 * math.pi * cutoff_freq)
		limit = int(round(6*sigma)) + 1
		xaxis = np.arange(-limit, limit+1) / sigma
		gaussian = scipy.stats.norm.pdf(xaxis) / sigma
		return np.abs(np.fft.fft(gaussian, n=N))
	else:
		freq_axis = np.fft.fftfreq(N, d=1/Utils.sampling_frequency)
		return scipy.stats.norm.pdf(freq_axis / cutoff_freq) * math.sqrt(2 * math.pi)
