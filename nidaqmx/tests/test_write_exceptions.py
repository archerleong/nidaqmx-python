import collections
import re

import numpy
import pytest
import random
import time

import nidaqmx
from nidaqmx.constants import (
    AcquisitionType, BusType, RegenerationMode)
from nidaqmx.error_codes import DAQmxErrors
from nidaqmx.utils import flatten_channel_string
from nidaqmx.tests.fixtures import x_series_device
from nidaqmx.tests.helpers import generate_random_seed


class TestWriteExceptions(object):
    """
    Contains a collection of pytest tests that validate the Write error behavior
    in the NI-DAQmx Python API.

    These tests use only a single X Series device by utilizing the internal
    loopback routes on the device.
    """

    def test_overwrite(self, x_series_device):
        # USB streaming is very tricky.
        if not (x_series_device.bus_type == BusType.PCIE or x_series_device.bus_type == BusType.PXIE):
            pytest.skip("Requires a plugin device.")

        number_of_samples = 100
        sample_rate = 1000
        fifo_size = 8191
        host_buffer_size = 1000

        with nidaqmx.Task() as write_task:
            samp_clk_terminal = '/{0}/Ctr0InternalOutput'.format(
                x_series_device.name)

            write_task.ao_channels.add_ao_voltage_chan(
                x_series_device.ao_physical_chans[0].name, max_val=10, min_val=-10)
            write_task.timing.cfg_samp_clk_timing(
                sample_rate, source=samp_clk_terminal, sample_mode=AcquisitionType.CONTINUOUS,
                samps_per_chan=number_of_samples)

            # Don't allow regeneration - this enables explicit hardware flow control.
            write_task.out_stream.regen_mode = RegenerationMode.DONT_ALLOW_REGENERATION

            # This is the only entrypoint that correctly sets number_of_samples_written in error
            # conditions prior to DAQmx 21.8.
            writer = nidaqmx.stream_writers.AnalogUnscaledWriter(write_task.out_stream, auto_start=False)

            # Fill up the host buffer first.
            initial_write_data = numpy.zeros((1, host_buffer_size), dtype=numpy.int16)
            writer.write_int16(initial_write_data)

            # Start the write task. All data from the host buffer should be in the FIFO.
            write_task.start()

            # Now write more data than can fit in the FIFO + host buffer.
            large_write_data = numpy.zeros((1, fifo_size*2), dtype=numpy.int16)
            with pytest.raises(nidaqmx.DaqWriteError) as timeout_exception:
                writer.write_int16(large_write_data, timeout=2.0)

            assert timeout_exception.value.error_code == DAQmxErrors.SAMPLES_CAN_NOT_YET_BE_WRITTEN
            # Some of the data should have been written successfully. This test doesn't
            # need to get into the nitty gritty device details on how much.
            assert timeout_exception.value.samps_per_chan_written > 0

    def test_overwrite_during_prime(self, x_series_device):
        # USB streaming is very tricky.
        if not (x_series_device.bus_type == BusType.PCIE or x_series_device.bus_type == BusType.PXIE):
            pytest.skip("Requires a plugin device.")

        number_of_samples = 100
        sample_rate = 1000
        fifo_size = 8191
        host_buffer_size = 1000
        total_buffer_size = fifo_size + host_buffer_size

        with nidaqmx.Task() as write_task:
            samp_clk_terminal = '/{0}/Ctr0InternalOutput'.format(
                x_series_device.name)

            write_task.ao_channels.add_ao_voltage_chan(
                x_series_device.ao_physical_chans[0].name, max_val=10, min_val=-10)
            write_task.timing.cfg_samp_clk_timing(
                sample_rate, source=samp_clk_terminal, sample_mode=AcquisitionType.CONTINUOUS,
                samps_per_chan=number_of_samples)

            # Don't allow regeneration - this enables explicit hardware flow control.
            write_task.out_stream.regen_mode = RegenerationMode.DONT_ALLOW_REGENERATION
            # Make the host buffer small.
            write_task.out_stream.output_buf_size = number_of_samples

            # This is the only entrypoint that correctly sets number_of_samples_written in error
            # conditions prior to DAQmx 21.8.
            writer = nidaqmx.stream_writers.AnalogUnscaledWriter(write_task.out_stream, auto_start=False)

            # This is more data than can be primed, so this should fail.
            initial_write_data = numpy.zeros((1, total_buffer_size*2), dtype=numpy.int16)
            with pytest.raises(nidaqmx.DaqWriteError) as timeout_exception:
                writer.write_int16(initial_write_data)

            assert timeout_exception.value.error_code == DAQmxErrors.NO_MORE_SPACE
            # The driver detects that the write will fail immediately, so no data was written.
            assert timeout_exception.value.samps_per_chan_written == 0
