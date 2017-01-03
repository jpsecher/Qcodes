import struct
import logging

import numpy as np
import array as arr

from time import sleep, localtime
from io import BytesIO
from qcodes import VisaInstrument, validators as vals
from pyvisa.errors import VisaIOError


log = logging.getLogger(__name__)

def parsestr(v):
    return v.strip().strip('"')


class Tektronix_AWG5014(VisaInstrument):
    """
    This is the QCoDeS driver for the Tektronix AWG5014
    Arbitrary Waveform Generator.

    The driver makes some assumptions on the settings of the instrument:

        - The output channels are always in Amplitude/Offset mode
        - The output markers are always in High/Low mode

    TODO:
        - Not all functionality is available in the driver
        - There is some double functionality
        - There are some inconsistensies between the name of a parameter and
          the name of the same variable in the tektronix manual

    In the future, we should consider the following:

        * Removing test_send??
        * That sequence element (SQEL) parameter functions exist but no
          corresponding parameters.

    """
    AWG_FILE_FORMAT_HEAD = {
        'SAMPLING_RATE': 'd',    # d
        'REPETITION_RATE': 'd',    # # NAME?
        'HOLD_REPETITION_RATE': 'h',    # True | False
        'CLOCK_SOURCE': 'h',    # Internal | External
        'REFERENCE_SOURCE': 'h',    # Internal | External
        'EXTERNAL_REFERENCE_TYPE': 'h',    # Fixed | Variable
        'REFERENCE_CLOCK_FREQUENCY_SELECTION': 'h',
        'REFERENCE_MULTIPLIER_RATE': 'h',    #
        'DIVIDER_RATE': 'h',   # 1 | 2 | 4 | 8 | 16 | 32 | 64 | 128 | 256
        'TRIGGER_SOURCE': 'h',    # Internal | External
        'INTERNAL_TRIGGER_RATE': 'd',    #
        'TRIGGER_INPUT_IMPEDANCE': 'h',    # 50 ohm | 1 kohm
        'TRIGGER_INPUT_SLOPE': 'h',    # Positive | Negative
        'TRIGGER_INPUT_POLARITY': 'h',    # Positive | Negative
        'TRIGGER_INPUT_THRESHOLD': 'd',    #
        'EVENT_INPUT_IMPEDANCE': 'h',    # 50 ohm | 1 kohm
        'EVENT_INPUT_POLARITY': 'h',    # Positive | Negative
        'EVENT_INPUT_THRESHOLD': 'd',
        'JUMP_TIMING': 'h',    # Sync | Async
        'INTERLEAVE': 'h',    # On |  This setting is stronger than .
        'ZEROING': 'h',    # On | Off
        'COUPLING': 'h',    # The Off | Pair | All setting is weaker than .
        'RUN_MODE': 'h',    # Continuous | Triggered | Gated | Sequence
        'WAIT_VALUE': 'h',    # First | Last
        'RUN_STATE': 'h',    # On | Off
        'INTERLEAVE_ADJ_PHASE': 'd',
        'INTERLEAVE_ADJ_AMPLITUDE': 'd',
    }
    AWG_FILE_FORMAT_CHANNEL = {
        # Include NULL.(Output Waveform Name for Non-Sequence mode)
        'OUTPUT_WAVEFORM_NAME_N': 's',
        'CHANNEL_STATE_N': 'h',  # On | Off
        'ANALOG_DIRECT_OUTPUT_N': 'h',  # On | Off
        'ANALOG_FILTER_N': 'h',  # Enum type.
        'ANALOG_METHOD_N': 'h',  # Amplitude/Offset, High/Low
        # When the Input Method is High/Low, it is skipped.
        'ANALOG_AMPLITUDE_N': 'd',
        # When the Input Method is High/Low, it is skipped.
        'ANALOG_OFFSET_N': 'd',
        # When the Input Method is Amplitude/Offset, it is skipped.
        'ANALOG_HIGH_N': 'd',
        # When the Input Method is Amplitude/Offset, it is skipped.
        'ANALOG_LOW_N': 'd',
        'MARKER1_SKEW_N': 'd',
        'MARKER1_METHOD_N': 'h',  # Amplitude/Offset, High/Low
        # When the Input Method is High/Low, it is skipped.
        'MARKER1_AMPLITUDE_N': 'd',
        # When the Input Method is High/Low, it is skipped.
        'MARKER1_OFFSET_N': 'd',
        # When the Input Method is Amplitude/Offset, it is skipped.
        'MARKER1_HIGH_N': 'd',
        # When the Input Method is Amplitude/Offset, it is skipped.
        'MARKER1_LOW_N': 'd',
        'MARKER2_SKEW_N': 'd',
        'MARKER2_METHOD_N': 'h',  # Amplitude/Offset, High/Low
        # When the Input Method is High/Low, it is skipped.
        'MARKER2_AMPLITUDE_N': 'd',
        # When the Input Method is High/Low, it is skipped.
        'MARKER2_OFFSET_N': 'd',
        # When the Input Method is Amplitude/Offset, it is skipped.
        'MARKER2_HIGH_N': 'd',
        # When the Input Method is Amplitude/Offset, it is skipped.
        'MARKER2_LOW_N': 'd',
        'DIGITAL_METHOD_N': 'h',  # Amplitude/Offset, High/Low
        # When the Input Method is High/Low, it is skipped.
        'DIGITAL_AMPLITUDE_N': 'd',
        # When the Input Method is High/Low, it is skipped.
        'DIGITAL_OFFSET_N': 'd',
        # When the Input Method is Amplitude/Offset, it is skipped.
        'DIGITAL_HIGH_N': 'd',
        # When the Input Method is Amplitude/Offset, it is skipped.
        'DIGITAL_LOW_N': 'd',
        'EXTERNAL_ADD_N': 'h',  # AWG5000 only
        'PHASE_DELAY_INPUT_METHOD_N':   'h',  # Phase/DelayInme/DelayInints
        'PHASE_N': 'd',  # When the Input Method is not Phase, it is skipped.
        # When the Input Method is not DelayInTime, it is skipped.
        'DELAY_IN_TIME_N': 'd',
        # When the Input Method is not DelayInPoint, it is skipped.
        'DELAY_IN_POINTS_N': 'd',
        'CHANNEL_SKEW_N': 'd',
        'DC_OUTPUT_LEVEL_N': 'd',  # V
    }

    def __init__(self, name, address, timeout=180, **kwargs):
        """
        Initializes the AWG5014.

        Args:
            name (string): name of the instrument
            address (string): GPIB or ethernet address as used by VISA
            timeout (float): visa timeout, in secs. long default (180)
                to accommodate large waveforms

        Returns:
            None
        """
        super().__init__(name, address, timeout=timeout, **kwargs)

        self._address = address

        self._values = {}
        self._values['files'] = {}

        self.add_function('reset', call_cmd='*RST')

        self.add_parameter('state',
                           get_cmd=self.get_state)
        self.add_parameter('run_mode',
                           get_cmd='AWGControl:RMODe?',
                           set_cmd='AWGControl:RMODe ' + '{}',
                           vals=vals.Enum('CONT', 'TRIG', 'SEQ', 'GAT'))
        self.add_parameter('ref_clock_source',
                           label='Reference clock source',
                           get_cmd='AWGControl:CLOCk:SOURce?',
                           set_cmd='AWGControl:CLOCk:SOURce ' + '{}',
                           vals=vals.Enum('INT', 'EXT'))
        self.add_parameter('DC_output',
                           label='DC Output (ON/OFF)',
                           get_cmd='AWGControl:DC:STATe?',
                           set_cmd='AWGControl:DC:STATe {}',
                           vals=vals.Ints(0, 1),
                           get_parser=int)

        # sequence parameter(s)
        self.add_parameter('sequence_length',
                           label='Sequence length',
                           get_cmd='SEQuence:LENGth?',
                           set_cmd='SEQuence:LENGth ' + '{}',
                           get_parser=int,
                           vals=vals.Ints(0, 8000),
                           docstring=(
                               """
                               This command sets the sequence length.
                               Use this command to create an
                               uninitialized sequence. You can also
                               use the command to clear all sequence
                               elements in a single action by passing
                               0 as the parameter. However, this
                               action cannot be undone so exercise
                               necessary caution. Also note that
                               passing a value less than the
                               sequence’s current length will cause
                               some sequence elements to be deleted at
                               the end of the sequence. For example if
                               self.get_sq_length returns 200 and you
                               subsequently set sequence_length to 21,
                               all sequence elements except the first
                               20 will be deleted.
                               """))

        # Trigger parameters #
        # Warning: `trigger_mode` is the same as `run_mode`, do not use! exists
        # solely for legacy purposes
        self.add_parameter('trigger_mode',
                           get_cmd='AWGControl:RMODe?',
                           set_cmd='AWGControl:RMODe ' + '{}',
                           vals=vals.Enum('CONT', 'TRIG', 'SEQ', 'GAT'))
        self.add_parameter('trigger_impedance',
                           label='Trigger impedance (Ohm)',
                           units='Ohm',
                           get_cmd='TRIGger:IMPedance?',
                           set_cmd='TRIGger:IMPedance ' + '{}',
                           vals=vals.Enum(50, 1000),
                           get_parser=float)
        self.add_parameter('trigger_level',
                           units='V',
                           label='Trigger level (V)',
                           get_cmd='TRIGger:LEVel?',
                           set_cmd='TRIGger:LEVel ' + '{:.3f}',
                           vals=vals.Numbers(-5, 5),
                           get_parser=float)
        self.add_parameter('trigger_slope',
                           get_cmd='TRIGger:SLOPe?',
                           set_cmd='TRIGger:SLOPe ' + '{}',
                           vals=vals.Enum('POS', 'NEG'))

        self.add_parameter('trigger_source',
                           get_cmd='TRIGger:SOURce?',
                           set_cmd='TRIGger:SOURce ' + '{}',
                           vals=vals.Enum('INT', 'EXT'))

        # Event parameters
        self.add_parameter('event_polarity',
                           get_cmd='EVENt:POL?',
                           set_cmd='EVENt:POL ' + '{}',
                           vals=vals.Enum('POS', 'NEG'))
        self.add_parameter('event_impedance',
                           label='Event impedance (Ohm)',
                           get_cmd='EVENt:IMPedance?',
                           set_cmd='EVENt:IMPedance ' + '{}',
                           vals=vals.Enum(50, 1000),
                           get_parser=float)
        self.add_parameter('event_level',
                           label='Event level (V)',
                           get_cmd='EVENt:LEVel?',
                           set_cmd='EVENt:LEVel ' + '{:.3f}',
                           vals=vals.Numbers(-5, 5),
                           get_parser=float)
        self.add_parameter('event_jump_timing',
                           get_cmd='EVENt:JTIMing?',
                           set_cmd='EVENt:JTIMing {}',
                           vals=vals.Enum('SYNC', 'ASYNC'))

        self.add_parameter('clock_freq',
                           label='Clock frequency (Hz)',
                           get_cmd='SOURce:FREQuency?',
                           set_cmd='SOURce:FREQuency ' + '{}',
                           vals=vals.Numbers(1e6, 1.2e9),
                           get_parser=float)

        self.add_parameter('setup_filename',
                           get_cmd='AWGControl:SNAMe?')

        # Channel parameters #
        for i in range(1, 5):
            amp_cmd = 'SOURce{}:VOLTage:LEVel:IMMediate:AMPLitude'.format(i)
            offset_cmd = 'SOURce{}:VOLTage:LEVel:IMMediate:OFFS'.format(i)
            state_cmd = 'OUTPUT{}:STATE'.format(i)
            waveform_cmd = 'SOURce{}:WAVeform'.format(i)
            directoutput_cmd = 'AWGControl:DOUTput{}:STATE'.format(i)
            filter_cmd = 'OUTPut{}:FILTer:FREQuency'.format(i)
            add_input_cmd = 'SOURce{}:COMBine:FEED'.format(i)
            dc_out_cmd = 'AWGControl:DC{}:VOLTage:OFFSet'.format(i)

            # Set channel first to ensure sensible sorting of pars
            self.add_parameter('ch{}_state'.format(i),
                               label='Status channel {}'.format(i),
                               get_cmd=state_cmd + '?',
                               set_cmd=state_cmd + ' {}',
                               vals=vals.Ints(0, 1))
            self.add_parameter('ch{}_amp'.format(i),
                               label='Amplitude channel {} (Vpp)'.format(i),
                               units='Vpp',
                               get_cmd=amp_cmd + '?',
                               set_cmd=amp_cmd + ' {:.6f}',
                               vals=vals.Numbers(0.02, 4.5),
                               get_parser=float)
            self.add_parameter('ch{}_offset'.format(i),
                               label='Offset channel {} (V)'.format(i),
                               units='V',
                               get_cmd=offset_cmd + '?',
                               set_cmd=offset_cmd + ' {:.3f}',
                               vals=vals.Numbers(-.1, .1),
                               get_parser=float)
            self.add_parameter('ch{}_waveform'.format(i),
                               label='Waveform channel {}'.format(i),
                               get_cmd=waveform_cmd + '?',
                               set_cmd=waveform_cmd + ' "{}"',
                               vals=vals.Strings(),
                               get_parser=parsestr)
            self.add_parameter('ch{}_direct_output'.format(i),
                               label='Direct output channel {}'.format(i),
                               get_cmd=directoutput_cmd + '?',
                               set_cmd=directoutput_cmd + ' {}',
                               vals=vals.Ints(0, 1))
            self.add_parameter('ch{}_add_input'.format(i),
                               label='Add input channel {}',
                               get_cmd=add_input_cmd + '?',
                               set_cmd=add_input_cmd + ' {}',
                               vals=vals.Enum('"ESIG"', '"ESIGnal"', '""'))
            self.add_parameter('ch{}_filter'.format(i),
                               label='Low pass filter channel {}'.format(i),
                               units='Hz',
                               get_cmd=filter_cmd + '?',
                               set_cmd=filter_cmd + ' {}',
                               vals=vals.Enum(20e6, 100e6, 9.9e37,
                                              'INF', 'INFinity'))
            self.add_parameter('ch{}_DC_out'.format(i),
                               label='DC output level channel {}'.format(i),
                               units='V',
                               get_cmd=dc_out_cmd + '?',
                               set_cmd=dc_out_cmd + ' {}',
                               vals=vals.Numbers(-3, 5),
                               get_parser=float)

            # Marker channels
            for j in range(1, 3):
                m_del_cmd = 'SOURce{}:MARKer{}:DELay'.format(i, j)
                m_high_cmd = ('SOURce{}:MARKer{}:VOLTage:' +
                              'LEVel:IMMediate:HIGH').format(i, j)
                m_low_cmd = ('SOURce{}:MARKer{}:VOLTage:' +
                             'LEVel:IMMediate:LOW').format(i, j)

                self.add_parameter(
                    'ch{}_m{}_del'.format(i, j),
                    label='Channel {} Marker {} delay (ns)'.format(i, j),
                    get_cmd=m_del_cmd + '?',
                    set_cmd=m_del_cmd + ' {:.3f}e-9',
                    vals=vals.Numbers(0, 1),
                    get_parser=float)
                self.add_parameter(
                    'ch{}_m{}_high'.format(i, j),
                    label='Channel {} Marker {} high level (V)'.format(i, j),
                    get_cmd=m_high_cmd + '?',
                    set_cmd=m_high_cmd + ' {:.3f}',
                    vals=vals.Numbers(-2.7, 2.7),
                    get_parser=float)
                self.add_parameter(
                    'ch{}_m{}_low'.format(i, j),
                    label='Channel {} Marker {} low level (V)'.format(i, j),
                    get_cmd=m_low_cmd + '?',
                    set_cmd=m_low_cmd + ' {:.3f}',
                    vals=vals.Numbers(-2.7, 2.7),
                    get_parser=float)

        self.set('trigger_impedance', 50)
        if self.get('clock_freq') != 1e9:
            log.warning('AWG clock freq not set to 1GHz')

        self.connect_message()

    # Functions
    def get_all(self, update=True):
        """
        Deprecated function. Please don't use.

        Function to get a snapshot of the state of all parameters and
        functions of the instrument.
        Note: methods of the Tektronix_AWG5014 class are not included.

        Args:
            update (bool): whether to return an updated state. Default: True

        Returns:

            dict: a JSON-serialisable dict with all information.

        Raises:
            DeprecationWarning
        """
        raise DeprecationWarning("Use snapshot(update=update) directly")
        return self.snapshot(update=update)

    def get_state(self):
        """
        This query returns the run state of the arbitrary waveform
        generator or the sequencer.

        Returns:
            str: either 'Idle', 'Waiting for trigger', or 'Running'.

        Raises:
            ValueError: if none of the three states above apply.
        """
        state = self.ask('AWGControl:RSTATe?')
        if state.startswith('0'):
            return 'Idle'
        elif state.startswith('1'):
            return 'Waiting for trigger'
        elif state.startswith('2'):
            return 'Running'
        else:
            raise ValueError(__name__ + (' : AWG in undefined ' +
                                         'state "{}"').format(state))

    def start(self):
        """Convenience function, identical to self.run()"""
        return self.run()

    def run(self):
        """
        This command initiates the output of a waveform or a sequence.
        This is equivalent to pressing Run/Stop button on the front panel.
        The instrument can be put in the run state only when output waveforms
        are assigned to channels.

        Returns:
            The output of self.get_state()
        """
        self.write('AWGControl:RUN')
        return self.get_state()

    def stop(self):
        """This command stops the output of a waveform or a sequence."""
        self.write('AWGControl:STOP')

    def force_trigger(self):
        """
        This command generates a trigger event. This is equivalent to
        pressing the Force Trigger button on front panel.
        """
        self.write('*TRG')

    def get_folder_contents(self, print_contents=True):
        """
        This query returns the current contents and state of the mass storage
        media (on the AWG Windows machine).

        Args:
            print_contents (bool): If True, the folder name and the query
                output are printed. Default: True.

        Returns:
            str: A comma-seperated string of the folder contents.
        """
        contents = self.ask('MMEMory:CATalog?')
        if print_contents:
            print('Current folder:', self.get_current_folder_name())
            print(contents
                  .replace(',"$', '\n$').replace('","', '\n')
                  .replace(',', '\t'))
        return contents

    def get_current_folder_name(self):
        """
        This query returns the current directory of the file system on the
        arbitrary waveform generator. The current directory for the
        programmatic interface is different from the currently selected
        directory in the Windows Explorer on the instrument.

        Returns:
            str: A string with the full path of the current folder.
        """
        return self.ask('MMEMory:CDIRectory?')

    def set_current_folder_name(self, file_path):
        """
        Set the current directory of the file system on the arbitrary
        waveform generator. The current directory for the programmatic
        interface is different from the currently selected directory in the
        Windows Explorer on the instrument.

        Args:
            file_path (str): The full path.

        Returns:
            tuple: tuple containing:
              - int: The number of bytes written,
              - enum 'Statuscode': whether the write was succesful
        """
        return self.visa_handle.write('MMEMory:CDIRectory "{}"'.format(file_path))

    def change_folder(self, folder):
        """Duplicate of self.set_current_folder_name"""
        return self.visa_handle.write('MMEMory:CDIRectory "\{}"'.format(folder))

    def goto_root(self):
        """
        Set the current directory of the file system on the arbitrary
        waveform generator to C: (the 'root' location in Windows).
        """
        self.write('MMEMory:CDIRectory "c:\\.."')

    def create_and_goto_dir(self, folder):
        """
        Set the current directory of the file system on the arbitrary
        waveform generator. Creates the directory if if doesn't exist.
        Queries the resulting folder for its contents.

        Args:
            folder (str): The path of the directory to set as current.
                Note: this function expects only root level directories.

        Returns:
            str: A comma-seperated string of the folder contents.
        """

        dircheck = '%s, DIR' % folder
        if dircheck in self.get_folder_contents():
            self.change_folder(folder)
            log.debug('Directory already exists')
            log.warning(('Directory already exists, ' +
                         'changed path to {}').format(folder))
            log.info('Contents of folder is ' +
                     '{}'.format(self.ask('MMEMory:cat?')))
        elif self.get_current_folder_name() == '"\\{}"'.format(folder):
            log.info('Directory already set to ' +
                     '{}'.format(folder))
        else:
            self.write('MMEMory:MDIRectory "\%s"' % folder)
            self.write('MMEMory:CDIRectory "\%s"' % folder)

        return self.get_folder_contents()

    def all_channels_on(self):
        """
        Set the state of all channels to be ON. Note: only channels with
        defined waveforms can be ON.
        """
        for i in range(1, 5):
            self.set('ch{}_state'.format(i), 1)

    def all_channels_off(self):
        """Set the state of all channels to be OFF."""
        for i in range(1, 5):
            self.set('ch{}_state'.format(i), 0)

    #####################
    # Sequences section #
    #####################

    def force_trigger_event(self):
        """
        This command generates a trigger event. Equivalent to
        self.force_trigger.
        """
        self.write('TRIGger:IMMediate')

    def force_event(self):
        """
        This command generates a forced event. This is used to generate the
        event when the sequence is waiting for an event jump. This is
        equivalent to pressing the Force Event button on the front panel of the
        instrument.
        """
        self.write('EVENt:IMMediate')

    def set_sqel_event_target_index(self, element_no, index):
        """
        This command sets the target index for
        the sequencer’s event jump operation. Note that this will take
        effect only when the event jump target type is set to
        INDEX.

        Args:
            element_no (int): The sequence element number
            index (int): The index to set the target to
        """
        self.write('SEQuence:' +
                   'ELEMent{}:JTARGet:INDex {}'.format(element_no, index))

    def set_sqel_goto_target_index(self, element_no, goto_to_index_no):
        """
        This command sets the target index for the GOTO command of the
        sequencer.  After generating the waveform specified in a
        sequence element, the sequencer jumps to the element specified
        as GOTO target. This is an unconditional jump. If GOTO target
        is not specified, the sequencer simply moves on to the next
        element. If the Loop Count is Infinite, the GOTO target which
        is specified in the element is not used. For this command to
        work, the goto state of the squencer must be ON and the
        sequence element must exist.
        Note that the first element of a sequence is taken to be 1 not 0.


        Args:
            element_no (int): The sequence element number
            goto_to_index_no (int) The target index number

        """
        self.write('SEQuence:' +
                   'ELEMent{}:GOTO:INDex {}'.format(element_no,
                                                    goto_to_index_no))

    def set_sqel_goto_state(self, element_no, goto_state):
        """
        This command sets the GOTO state of the sequencer for the specified
        sequence element.

        Args:
            element_no (int): The sequence element number
            goto_state (int): The GOTO state of the sequencer. Must be either
                0 (OFF) or 1 (ON).
        """
        allowed_states = [0, 1]
        if goto_state not in allowed_states:
            log.warning(('{} not recognized as a valid goto' +
                         ' state. Setting to 0 (OFF).').format(goto_state))
            goto_state = 0
        self.write('SEQuence:ELEMent{}:GOTO:STATe {}'.format(element_no,
                                                             int(goto_state)))

    def set_sqel_loopcnt_to_inf(self, element_no, state=1):
        """
        This command sets the infinite looping state for a sequence
        element. When an infinite loop is set on an element, the
        sequencer continuously executes that element. To break the
        infinite loop, issue self.stop()

        Args:
            element_no (int): The sequence element number
            state (int): The infinite loop state. Must be either 0 (OFF) or
                1 (ON).
        """
        allowed_states = [0, 1]
        if state not in allowed_states:
            log.warning(('{} not recognized as a valid loop' +
                         '  state. Setting to 0 (OFF).').format(state))
            state = 0

        self.write('SEQuence:ELEMent{}:LOOP:INFinite {}'.format(element_no,
                                                                int(state)))

    def get_sqel_loopcnt(self, element_no=1):
        """
        This query returns the loop count (number of repetitions) of a
        sequence element. Loop count setting for an element is ignored
        if the infinite looping state is set to ON.

        Args:
            element_no (int): The sequence element number. Default: 1.
        """
        return self.ask('SEQuence:ELEMent{}:LOOP:COUNt?'.format(element_no))

    def set_sqel_loopcnt(self, loopcount, element_no=1):
        """
        This command sets the loop count. Loop count setting for an
        element is ignored if the infinite looping state is set to ON.

        Args:
            loopcount (int): The number of times the sequence is being output.
                The maximal possible number is 65536, beyond that: infinity.
            element_no (int): The sequence element number. Default: 1.
        """
        self.write('SEQuence:ELEMent{}:LOOP:COUNt {}'.format(element_no,
                                                             loopcount))

    def set_sqel_waveform(self, waveform_name, channel, element_no=1):
        """
        This command sets the waveform for a sequence element on the specified
        channel.

        Args:
            waveform_name (str): Name of the waveform. Must be in the waveform
                list (either User Defined or Predefined).
            channel (int): The output channel (1-4)
            element_no (int): The sequence element number. Default: 1.
        """
        self.write('SEQuence:ELEMent{}:WAVeform{} "{}"'.format(element_no,
                                                               channel,
                                                               waveform_name))

    def get_sqel_waveform(self, channel, element_no=1):
        """
        This query returns the waveform for a sequence element on the
        specified channel.

        Args:
            channel (int): The output channel (1-4)
            element_no (int): The sequence element number. Default: 1.

        Returns:
            str: The name of the waveform.
        """
        return self.ask('SEQuence:ELEMent{}:WAVeform{}?'.format(element_no,
                                                                channel))

    def set_sqel_trigger_wait(self, element_no, state=1):
        """
        This command sets the wait trigger state for an element. Send
        a trigger signal in one of the following ways:
          * By using an external trigger signal.
          * By pressing the “Force Trigger” button on the front panel
          * By using self.force_trigger or self.force_trigger_event

        Args:
            element_no (int): The sequence element number.
            state (int): The wait trigger state. Must be either 0 (OFF)
                or 1 (ON). Default: 1.

        Returns:
            str: The current state (after setting it).

        """
        self.write('SEQuence:ELEMent{}:TWAit {}'.format(element_no, state))
        return self.get_sqel_trigger_wait(element_no)

    def get_sqel_trigger_wait(self, element_no):
        """
        This query returns the wait trigger state for an element. Send
        a trigger signal in one of the following ways:
          * By using an external trigger signal.
          * By pressing the “Force Trigger” button on the front panel
          * By using self.force_trigger or self.force_trigger_event

        Args:
            element_no (int): The sequence element number.

        Returns:
            str: The current state. Example: '1'.
        """
        return self.ask('SEQuence:ELEMent{}:TWAit?'.format(element_no))

    def set_sqel_event_jump_target_index(self, element_no, jtar_index_no):
        """Duplicate of set_sqel_event_target_index"""
        self.write('SEQuence:ELEMent{}:JTARget:INDex {}'.format(element_no,
                                                                jtar_index_no))

    def set_sqel_event_jump_type(self, element_no, jtar_state):
        """
        This command sets the event jump target type for the jump for
        the specified sequence element.  Generate an event in one of
        the following ways:

        * By connecting an external cable to instrument rear panel
          for external event.
        * By pressing the Force Event button on the
          front panel.
        * By using self.force_event

        Args:
            element_no (int): The sequence element number
            jtar_state (str): The jump target type. Must be either 'INDEX',
                'NEXT', or 'OFF'.
        """
        self.write('SEQuence:ELEMent{}:JTARget:TYPE {}'.format(element_no,
                                                               jtar_state))

    def get_sq_mode(self):
        """
        This query returns the type of the arbitrary waveform
        generator's sequencer. The sequence is executed by the
        hardware sequencer whenever possible.

        Returns:
            str: Either 'HARD' or 'SOFT' indicating that the instrument is in\
              either hardware or software sequencer mode.
        """
        return self.ask('AWGControl:SEQuence:TYPE?')

    def get_sq_position(self):
        """
        This query returns the current position of the sequencer.

        Returns:
            str: The current sequencer position.

        """
        return self.ask('AWGControl:SEQuence:POSition?')

    def sq_forced_jump(self, jump_index_no):
        """
        This command forces the sequencer to jump to the specified
        element index. This is called a Force jump. This command does
        not require an event for executing the jump. Also, the Jump
        target specified for event jump is not used here.

        Args:
            jump_index_no (int): The target index to jump to.
        """
        self.write('SEQuence:JUMP:IMMediate {}'.format(jump_index_no))

    ######################
    # AWG file functions #
    ######################

    def _pack_record(self, name, value, dtype):
        """
        packs awg_file record into a struct in the folowing way:
            struct.pack(fmtstring, namesize, datasize, name, data)
        where fmtstring = '<IIs"dtype"'

        The file record format is as follows:
        Record Name Size:        (32-bit unsigned integer)
        Record Data Size:        (32-bit unsigned integer)
        Record Name:             (ASCII) (Include NULL.)
        Record Data
        For details see "File and Record Format" in the AWG help

        < denotes little-endian encoding, I and other dtypes are format
        characters denoted in the documentation of the struct package

        Args:
            name (str): Name of the record (Example: 'MAGIC' or
            'SAMPLING_RATE')
            value (int): The value of that record.
            dtype (str): String specifying the data type of the record.
                Allowed values: 'h', 'd', 's'.
        """
        if len(dtype) == 1:
            record_data = struct.pack('<' + dtype, value)
        else:
            if dtype[-1] == 's':
                record_data = value.encode('ASCII')
            else:
                record_data = struct.pack('<' + dtype, *value)

        # the zero byte at the end the record name is the "(Include NULL.)"
        record_name = name.encode('ASCII') + b'\x00'
        record_name_size = len(record_name)
        record_data_size = len(record_data)
        size_struct = struct.pack('<II', record_name_size, record_data_size)
        packed_record = size_struct + record_name + record_data

        return packed_record

    def generate_sequence_cfg(self):
        """
        This function is used to generate a config file, that is used when
        generating sequence files, from existing settings in the awg.
        Querying the AWG for these settings takes ~0.7 seconds
        """
        log.info('Generating sequence_cfg')

        AWG_sequence_cfg = {
            'SAMPLING_RATE': self.get('clock_freq'),
            'CLOCK_SOURCE': (1 if self.ask('AWGControl:CLOCk:' +
                                           'SOURce?').startswith('INT')
                             else 2),  # Internal | External
            'REFERENCE_SOURCE': (1 if self.ask('SOURce1:ROSCillator:' +
                                               'SOURce?').startswith('INT')
                                 else 2),  # Internal | External
            'EXTERNAL_REFERENCE_TYPE':   1,  # Fixed | Variable
            'REFERENCE_CLOCK_FREQUENCY_SELECTION': 1,
            # 10 MHz | 20 MHz | 100 MHz
            'TRIGGER_SOURCE':   1 if
            self.get('trigger_source').startswith('EXT') else 2,
            # External | Internal
            'TRIGGER_INPUT_IMPEDANCE': (1 if self.get('trigger_impedance') ==
                                        50. else 2),  # 50 ohm | 1 kohm
            'TRIGGER_INPUT_SLOPE': (1 if self.get('trigger_slope').startswith(
                                    'POS') else 2),  # Positive | Negative
            'TRIGGER_INPUT_POLARITY': (1 if self.ask('TRIGger:' +
                                                     'POLarity?').startswith(
                                       'POS') else 2),  # Positive | Negative
            'TRIGGER_INPUT_THRESHOLD':  self.get('trigger_level'),  # V
            'EVENT_INPUT_IMPEDANCE':   (1 if self.get('event_impedance') ==
                                        50. else 2),  # 50 ohm | 1 kohm
            'EVENT_INPUT_POLARITY':  (1 if self.get('event_polarity').startswith(
                                      'POS') else 2),  # Positive | Negative
            'EVENT_INPUT_THRESHOLD':   self.get('event_level'),  # V
            'JUMP_TIMING':   (1 if
                              self.get('event_jump_timing').startswith('SYNC')
                              else 2),  # Sync | Async
            'RUN_MODE':   4,  # Continuous | Triggered | Gated | Sequence
            'RUN_STATE':  0,  # On | Off
        }
        return AWG_sequence_cfg

    def generate_channel_cfg(self):
        """
        Function to query if the current channel settings that have
        been changed from their default value and put them in a
        dictionary that can easily be written into an awg file, so as
        to prevent said awg file from falling back to default values.
        (See self.generate_awg_file and self.AWG_FILE_FORMAT_CHANNEL)
        NOTE: This only works for settings changed via the corresponding
        QCoDeS parameter.

        Returns:
            dict: A dict with the current setting for each entry in
            AWG_FILE_FORMAT_HEAD iff this entry applies to the
            AWG5014 AND has been changed from its default value.
        """
        log.info('Getting channel configurations.')

        dirouts = [self.ch1_direct_output.get_latest(),
                   self.ch2_direct_output.get_latest(),
                   self.ch3_direct_output.get_latest(),
                   self.ch4_direct_output.get_latest()]

        # the return value of the parameter is different from what goes
        # into the .awg file, so we translate it
        filtertrans = {20e6: 1, 100e6: 3, 9.9e37: 10,
                       'INF': 10, 'INFinity': 10, None: None}
        filters = [filtertrans[self.ch1_filter.get_latest()],
                   filtertrans[self.ch2_filter.get_latest()],
                   filtertrans[self.ch3_filter.get_latest()],
                   filtertrans[self.ch4_filter.get_latest()]]

        amps = [self.ch1_amp.get_latest(),
                self.ch2_amp.get_latest(),
                self.ch3_amp.get_latest(),
                self.ch4_amp.get_latest()]

        offsets = [self.ch1_offset.get_latest(),
                   self.ch2_offset.get_latest(),
                   self.ch3_offset.get_latest(),
                   self.ch4_offset.get_latest()]

        mrk1highs = [self.ch1_m1_high.get_latest(),
                     self.ch2_m1_high.get_latest(),
                     self.ch3_m1_high.get_latest(),
                     self.ch4_m1_high.get_latest()]

        mrk1lows = [self.ch1_m1_low.get_latest(),
                    self.ch2_m1_low.get_latest(),
                    self.ch3_m1_low.get_latest(),
                    self.ch4_m1_low.get_latest()]

        mrk2highs = [self.ch1_m2_high.get_latest(),
                     self.ch2_m2_high.get_latest(),
                     self.ch3_m2_high.get_latest(),
                     self.ch4_m2_high.get_latest()]

        mrk2lows = [self.ch1_m2_low.get_latest(),
                    self.ch2_m2_low.get_latest(),
                    self.ch3_m2_low.get_latest(),
                    self.ch4_m2_low.get_latest()]

        # the return value of the parameter is different from what goes
        # into the .awg file, so we translate it
        addinptrans = {'"ESIG"': 1, '""': 0, None: None}
        addinputs = [addinptrans[self.ch1_add_input.get_latest()],
                     addinptrans[self.ch2_add_input.get_latest()],
                     addinptrans[self.ch3_add_input.get_latest()],
                     addinptrans[self.ch4_add_input.get_latest()]]

        # the return value of the parameter is different from what goes
        # into the .awg file, so we translate it
        def mrkdeltrans(x):
            if x is None:
                return None
            else:
                return x*1e-9
        mrk1delays = [mrkdeltrans(self.ch1_m1_del.get_latest()),
                      mrkdeltrans(self.ch2_m1_del.get_latest()),
                      mrkdeltrans(self.ch3_m1_del.get_latest()),
                      mrkdeltrans(self.ch4_m1_del.get_latest())]
        mrk2delays = [mrkdeltrans(self.ch1_m2_del.get_latest()),
                      mrkdeltrans(self.ch2_m2_del.get_latest()),
                      mrkdeltrans(self.ch3_m2_del.get_latest()),
                      mrkdeltrans(self.ch4_m2_del.get_latest())]

        AWG_channel_cfg = {}

        for chan in range(1, 5):
            if dirouts[chan-1] is not None:
                AWG_channel_cfg.update({'ANALOG_DIRECT_OUTPUT_{}'.format(chan):
                                        int(dirouts[chan-1])})
            if filters[chan-1] is not None:
                AWG_channel_cfg.update({'ANALOG_FILTER_{}'.format(chan):
                                        filters[chan-1]})
            if amps[chan-1] is not None:
                AWG_channel_cfg.update({'ANALOG_AMPLITUDE_{}'.format(chan):
                                        amps[chan-1]})
            if offsets[chan-1] is not None:
                AWG_channel_cfg.update({'ANALOG_OFFSET_{}'.format(chan):
                                        offsets[chan-1]})
            if mrk1highs[chan-1] is not None:
                AWG_channel_cfg.update({'MARKER1_HIGH_{}'.format(chan):
                                        mrk1highs[chan-1]})
            if mrk1lows[chan-1] is not None:
                AWG_channel_cfg.update({'MARKER1_LOW_{}'.format(chan):
                                        mrk1lows[chan-1]})
            if mrk2highs[chan-1] is not None:
                AWG_channel_cfg.update({'MARKER2_HIGH_{}'.format(chan):
                                        mrk2highs[chan-1]})
            if mrk2lows[chan-1] is not None:
                AWG_channel_cfg.update({'MARKER2_LOW_{}'.format(chan):
                                        mrk2lows[chan-1]})
            if mrk1delays[chan-1] is not None:
                AWG_channel_cfg.update({'MARKER1_SKEW_{}'.format(chan):
                                        mrk1delays[chan-1]})
            if mrk2delays[chan-1] is not None:
                AWG_channel_cfg.update({'MARKER2_SKEW_{}'.format(chan):
                                        mrk2delays[chan-1]})
            if addinputs[chan-1] is not None:
                AWG_channel_cfg.update({'EXTERNAL_ADD_{}'.format(chan):
                                        addinputs[chan-1]})

        return AWG_channel_cfg

    def generate_awg_file(self,
                          packed_waveforms, wfname_l, nrep, trig_wait,
                          goto_state, jump_to, channel_cfg,
                          sequence_cfg=None,
                          preservechannelsettings=False):
        """
        This function generates an .awg-file for uploading to the AWG.
        The .awg-file contains a waveform list, full sequencing information
        and instrument configuration settings.

        Args:
            packed_waveforms (dict): dictionary containing packed waveforms
            with keys wfname_l

            wfname_l (numpy.ndarray): array of waveform names, e.g.
                array([[segm1_ch1,segm2_ch1..], [segm1_ch2,segm2_ch2..],...])

            nrep_l (list): list of len(segments) of integers specifying the
                no. of repetions per sequence element.
                Allowed values: 1 to 65536.

            wait_l (list): list of len(segments) of integers specifying the
                trigger wait state of each sequence element.
                Allowed values: 0 (OFF) or 1 (ON).

            goto_l (list): list of len(segments) of integers specifying the
                goto state of each sequence element. Allowed values: 0 to 65536
                (0 means next)

            logic_jump_l (list): list of len(segments) of integers specifying
                the logic jump state for each sequence element. Allowed values:
                0 (OFF) or 1 (ON).

            channel_cfg (dict): dictionary of valid channel configuration
                records. See self.AWG_FILE_FORMAT_CHANNEL for a complete
                overview of valid configuration parameters.

            preservechannelsettings (bool): If True, the current channel
                settings are queried from the instrument and added to
                channel_cfg (does not overwrite). Default: False.

            sequence_cfg (dict): dictionary of valid head configuration records
                     (see self.AWG_FILE_FORMAT_HEAD)
                     When an awg file is uploaded these settings will be set
                     onto the AWG, any parameter not specified will be set to
                     its default value (even overwriting current settings)

        for info on filestructure and valid record names, see AWG Help,
        File and Record Format (Under 'Record Name List' in Help)
        """
        if preservechannelsettings:
            channel_settings = self.generate_channel_cfg()
            for setting in channel_settings:
                if setting not in channel_cfg:
                    channel_cfg.update({setting: channel_settings[setting]})

        timetuple = tuple(np.array(localtime())[[0, 1, 8, 2, 3, 4, 5, 6, 7]])

        # general settings
        head_str = BytesIO()
        bytes_to_write = (self._pack_record('MAGIC', 5000, 'h') +
                          self._pack_record('VERSION', 1, 'h'))
        head_str.write(bytes_to_write)
        # head_str.write(string(bytes_to_write))

        if sequence_cfg is None:
            sequence_cfg = self.generate_sequence_cfg()

        for k in list(sequence_cfg.keys()):
            if k in self.AWG_FILE_FORMAT_HEAD:
                head_str.write(self._pack_record(k, sequence_cfg[k],
                                                 self.AWG_FILE_FORMAT_HEAD[k]))
            else:
                log.warning('AWG: ' + k +
                            ' not recognized as valid AWG setting')
        # channel settings
        ch_record_str = BytesIO()
        for k in list(channel_cfg.keys()):
            ch_k = k[:-1] + 'N'
            if ch_k in self.AWG_FILE_FORMAT_CHANNEL:
                ch_record_str.write(self._pack_record(k, channel_cfg[k],
                                                      self.AWG_FILE_FORMAT_CHANNEL[ch_k]))
            else:
                log.warning('AWG: ' + k +
                            ' not recognized as valid AWG channel setting')

        # waveforms
        ii = 21

        wf_record_str = BytesIO()
        wlist = list(packed_waveforms.keys())
        wlist.sort()
        for wf in wlist:
            wfdat = packed_waveforms[wf]
            lenwfdat = len(wfdat)

            wf_record_str.write(
                self._pack_record('WAVEFORM_NAME_{}'.format(ii), wf + '\x00',
                                  '{}s'.format(len(wf + '\x00'))) +
                self._pack_record('WAVEFORM_TYPE_{}'.format(ii), 1, 'h') +
                self._pack_record('WAVEFORM_LENGTH_{}'.format(ii),
                                  lenwfdat, 'l') +
                self._pack_record('WAVEFORM_TIMESTAMP_{}'.format(ii),
                                  timetuple[:-1], '8H') +
                self._pack_record('WAVEFORM_DATA_{}'.format(ii), wfdat,
                                  '{}H'.format(lenwfdat)))
            ii += 1

        # sequence
        kk = 1
        seq_record_str = BytesIO()

        for segment in wfname_l.transpose():

            seq_record_str.write(
                self._pack_record('SEQUENCE_WAIT_{}'.format(kk),
                                  trig_wait[kk - 1], 'h') +
                self._pack_record('SEQUENCE_LOOP_{}'.format(kk),
                                  int(nrep[kk - 1]), 'l') +
                self._pack_record('SEQUENCE_JUMP_{}'.format(kk),
                                  jump_to[kk - 1], 'h') +
                self._pack_record('SEQUENCE_GOTO_{}'.format(kk),
                                  goto_state[kk - 1], 'h'))
            for wfname in segment:
                if wfname is not None:
                    # TODO (WilliamHPNielsen): maybe infer ch automatically
                    # from the data size?
                    ch = wfname[-1]
                    seq_record_str.write(
                        self._pack_record('SEQUENCE_WAVEFORM_NAME_CH_' + ch
                                          + '_{}'.format(kk), wfname + '\x00',
                                          '{}s'.format(len(wfname + '\x00')))
                    )
            kk += 1

        awg_file = (head_str.getvalue() + ch_record_str.getvalue() +
                    wf_record_str.getvalue() + seq_record_str.getvalue())
        return awg_file

    def send_awg_file(self, filename, awg_file, verbose=False):
        """
        Writes an .awg-file onto the disk of the AWG.
        Overwrites existing files.

        Args:
            filename (str): The name that the file will get on
                the AWG.
            awg_file (bytes): A byte sequence containing the awg_file.
                Usually the output of self.generate_awg_file.
            verbose (bool): A boolean to allow/suppress printing of messages
                about the status of the filw writing. Default: False.
        """
        if verbose:
            print('Writing to:',
                  self.ask('MMEMory:CDIRectory?').replace('\n', '\ '),
                  filename)
        # Header indicating the name and size of the file being send
        name_str = 'MMEMory:DATA "{}",'.format(filename).encode('ASCII')
        size_str = ('#' + str(len(str(len(awg_file)))) +
                    str(len(awg_file))).encode('ASCII')
        mes = name_str + size_str + awg_file
        self.visa_handle.write_raw(mes)

    def load_awg_file(self, filename):
        """
        Loads an .awg-file from the disc of the AWG into the AWG memory.
        This may overwrite all instrument settings, the waveform list, and the
        sequence in the sequencer.

        Args:
            filename (str): The filename of the .awg-file to load.
        """
        s = 'AWGControl:SREStore "{}"'.format(filename)
        log.debug('Loading awg file using {}'.format(s))
        self.visa_handle.write_raw(s)
        # we must update the appropriate parameter(s) for the sequence
        self.sequence_length.set(self.sequence_length.get())

    def make_send_and_load_awg_file(self, waveforms, m1s, m2s,
                                    nreps, trig_waits,
                                    goto_states, jump_tos,
                                    channels=None,
                                    filename='customawgfile.awg',
                                    preservechannelsettings=True):
        """
        Makes an .awg-file, sends it to the AWG and loads it. The .awg-file
        is uploaded to C:\\\\Users\\\\OEM\\\\Documents. The waveforms appear in
        the user defined waveform list with names wfm001ch1, wfm002ch1, ...

        Args:
            waveforms (list): A list of the waveforms to upload. The list
                should be filled like so:
                [[wfm1ch1, wfm2ch1, ...], [wfm1ch2, wfm2ch2], ...]
                Each waveform should be a numpy array with values in the range
                -1 to 1 (inclusive). If you do not wish to send waveforms to
                channels 1 and 2, use the channels parameter.

            m1s (list): A list of marker 1's. The list should be filled
                like so:
                [[elem1m1ch1, elem2m1ch1, ...], [elem1m1ch2, elem2m1ch2], ...]
                Each marker should be a numpy array containing only 0's and 1's

            m2s (list): A list of marker 2's. The list should be filled
                like so:
                [[elem1m2ch1, elem2m2ch1, ...], [elem1m2ch2, elem2m2ch2], ...]
                Each marker should be a numpy array containing only 0's and 1's

            nreps (list): List of integers specifying the no. of
                repetions per sequence element.  Allowed values: 1 to
                65536.

            trig_waits (list): List of len(segments) of integers specifying the
                trigger wait state of each sequence element.
                Allowed values: 0 (OFF) or 1 (ON).

            goto_states (list): List of len(segments) of integers
                specifying the goto state of each sequence
                element. Allowed values: 0 to 65536 (0 means next)

            jump_tos (list): List of len(segments) of integers specifying
                the logic jump state for each sequence element. Allowed values:
                0 (OFF) or 1 (ON).

            channels (list): List of channels to send the waveforms to.
                Example: [1, 3, 2]

            filename (str): The name of the .awg-file. Should end with the .awg
                extension. Default: 'customawgfile.awg'

            preservechannelsettings (bool): If True, the current channel
                settings are found from the parameter history and added to
                the .awg file. Else, channel settings are reset to the factory
                default values. Default: True.
        """

        # by default, an unusable directory is targeted on the AWG
        self.visa_handle.write('MMEMory:CDIRectory ' +
                               '"C:\\Users\\OEM\\Documents"')
        
        # waveform names and the dictionary of packed waveforms
        packed_wfs = {}
        waveform_names = []
        if not isinstance(waveforms[0], list):
            waveforms = [waveforms]
            m1s = [m1s]
            m2s = [m2s]
        for ii in range(len(waveforms)):
            namelist = []
            for jj in range(len(waveforms[ii])):
                if channels is None:
                    thisname = 'wfm{:03d}ch{}'.format(jj+1, ii+1)
                else:
                    thisname = 'wfm{:03d}ch{}'.format(jj+1, channels[ii])
                namelist.append(thisname)
                package = self.pack_waveform(waveforms[ii][jj],
                                             m1s[ii][jj],
                                             m2s[ii][jj])
                packed_wfs[thisname] = package
            waveform_names.append(namelist)

        wavenamearray = np.array(waveform_names, dtype='str')

        channel_cfg = {}

        awg_file = self.generate_awg_file(packed_wfs,
                                          wavenamearray,
                                          nreps, trig_waits, goto_states,
                                          jump_tos, channel_cfg,
                                          preservechannelsettings=preservechannelsettings)

        self.send_awg_file(filename, awg_file)
        currentdir = self.visa_handle.query('MMEMory:CDIRectory?')
        currentdir = currentdir.replace('"', '')
        currentdir = currentdir.replace('\n', '\\')
        loadfrom = '{}{}'.format(currentdir, filename)
        self.load_awg_file(loadfrom)

    def get_error(self):
        """
        This function retrieves and returns data from the error and
        event queues.

        Returns:
            str: String containing the error/event number, the error/event\
                description.
        """
        return self.ask('SYSTEM:ERRor:NEXT?')

    def pack_waveform(self, wf, m1, m2):
        """
        Converts/packs a waveform and two markers into a 16-bit format
        according to the AWG Integer format specification.
        The waveform occupies 14 bits and the markers one bit each.
        See Table 2-25 in the Programmer's manual for more information

        Since markers can only be in one of two states, the marker input
        arrays should consist only of 0's and 1's.

        Args:
            wf (numpy.ndarray): A numpy array containing the waveform. The
                data type of wf is unimportant.
            m1 (numpy.ndarray): A numpy array containing the first marker.
            m2 (numpy.ndarray): A numpy array containing the second marker.

        Returns:
            numpy.ndarray: An array of unsigned 16 bit integers.

        Raises:
            Exception: if the lengths of w, m1, and m2 don't match
            TypeError: if the waveform contains values outside (-1, 1)
            TypeError: if the markers contain values that are not 0 or 1
        """

        # Input validation
        if (not((len(wf) == len(m1)) and ((len(m1) == len(m2))))):
            raise Exception('error: sizes of the waveforms do not match')
        if min(wf) < -1 or max(wf) > 1:
            raise TypeError('Waveform values out of bonds.' +
                            ' Allowed values: -1 to 1 (inclusive)')
        if (list(m1).count(0)+list(m1).count(1)) != len(m1):
            raise TypeError('Marker 1 contains invalid values.' +
                            ' Only 0 and 1 are allowed')
        if (list(m2).count(0)+list(m2).count(1)) != len(m2):
            raise TypeError('Marker 2 contains invalid values.' +
                            ' Only 0 and 1 are allowed')

        wflen = len(wf)
        packed_wf = np.zeros(wflen, dtype=np.uint16)
        packed_wf += np.uint16(np.round(wf * 8191) + 8191 +
                               np.round(16384 * m1) +
                               np.round(32768 * m2))
        if len(np.where(packed_wf == -1)[0]) > 0:
            print(np.where(packed_wf == -1))
        return packed_wf

    ###########################
    # Waveform file functions #
    ###########################

    def _file_dict(self, wf, m1, m2, clock):
        """
        Make a file dictionary as used by self.send_waveform_to_list

        Args:
            wf (numpy.ndarray): A numpy array containing the waveform. The
                data type of wf is unimportant.
            m1 (numpy.ndarray): A numpy array containing the first marker.
            m2 (numpy.ndarray): A numpy array containing the second marker.
            clock (float): The desired clock frequency

        Returns:
            dict: A dictionary with keys 'w', 'm1', 'm2', 'clock_freq', and
                'numpoints' and corresponding values.
        """

        outdict = {
            'w': wf,
            'm1': m1,
            'm2': m2,
            'clock_freq': clock,
            'numpoints': len(wf)
        }

        return outdict

    def delete_all_waveforms_from_list(self):
        """
        Delete all user-defined waveforms in the list in a single
        action. Note that there is no “UNDO” action once the waveforms
        are deleted. Use caution before issuing this command.

        If the deleted waveform(s) is (are) currently loaded into
        waveform memory, it (they) is (are) unloaded. If the RUN state
        of the instrument is ON, the state is turned OFF. If the
        channel is on, it will be switched off.
        """
        self.write('WLISt:WAVeform:DELete ALL')

    def get_filenames(self):
        """Duplicate of self.get_folder_contents"""
        return self.ask('MMEMory:CATalog?')

    def send_DC_pulse(self, DC_channel_number, set_level, length):
        """
        Sets the DC level on the specified channel, waits a while and then
        resets it to what it was before.

        Note: Make sure that the output DC state is ON.

        Args:
            DC_channel_number (int): The channel number (1-4).
            set_level (float): The voltage level to set to (V).
            length (float): The time to wait before resetting (s).
        """
        DC_channel_number -= 1
        chandcs = [self.ch1_DC_out, self.ch2_DC_out, self.ch3_DC_out,
                   self.ch4_DC_out]

        restore = self.chandcs[DC_channel_number].get()
        self.chandcs[DC_channel_number].set(set_level)
        sleep(length)
        self.chandcs[DC_channel_number].set(restore)

    def is_awg_ready(self):
        """
        Assert if the AWG is ready.

        Returns:
            bool: True, irrespective of anything.
        """
        try:
            self.ask('*OPC?')
        # makes the awg read again if there is a timeout
        except Exception as e:
            log.warning(e)
            log.warning('AWG is not ready')
            self.visa_handle.read()
        return True

    def send_waveform_to_list(self, w, m1, m2, wfmname):
        """
        Send a single complete waveform directly to the "User defined"
        waveform list (prepend it). The data type of the input arrays
        is unimportant, but the marker arrays must contain only 1's
        and 0's.

        Args:
            w (numpy.ndarray): The waveform
            m1 (numpy.ndarray): Marker1
            m2 (numpy.ndarray): Marker2
            wfmname (str): waveform name

        Raises:
            Exception: if the lengths of w, m1, and m2 don't match
            TypeError: if the waveform contains values outside (-1, 1)
            TypeError: if the markers contain values that are not 0 or 1
        """
        log.debug('Sending waveform {} to instrument'.format(wfmname))
        # Check for errors
        dim = len(w)

        # Input validation
        if (not((len(w) == len(m1)) and ((len(m1) == len(m2))))):
            raise Exception('error: sizes of the waveforms do not match')
        if min(w) < -1 or max(w) > 1:
            raise TypeError('Waveform values out of bonds.' +
                            ' Allowed values: -1 to 1 (inclusive)')
        if (list(m1).count(0)+list(m1).count(1)) != len(m1):
            raise TypeError('Marker 1 contains invalid values.' +
                            ' Only 0 and 1 are allowed')
        if (list(m2).count(0)+list(m2).count(1)) != len(m2):
            raise TypeError('Marker 2 contains invalid values.' +
                            ' Only 0 and 1 are allowed')

        self._values['files'][wfmname] = self._file_dict(w, m1, m2, None)

        # if we create a waveform with the same name but different size,
        # it will not get over written
        # Delete the possibly existing file (will do nothing if the file
        # doesn't exist
        s = 'WLISt:WAVeform:DEL "{}"'.format(wfmname)
        self.write(s)

        # create the waveform
        s = 'WLISt:WAVeform:NEW "{}",{:d},INTEGER'.format(wfmname, dim)
        self.write(s)
        # Prepare the data block
        number = ((2**13-1) + (2**13-1) * w + 2**14 *
                  np.array(m1) + 2**15 * np.array(m2))
        number = number.astype('int')
        ws = arr.array('H', number)

        ws = ws.tobytes()
        s1 = 'WLISt:WAVeform:DATA "{}",'.format(wfmname)
        s1 = s1.encode('UTF-8')
        s3 = ws
        s2 = '#' + str(len(str(len(s3)))) + str(len(s3))
        s2 = s2.encode('UTF-8')

        mes = s1 + s2 + s3
        self.visa_handle.write_raw(mes)

    def clear_message_queue(self, verbose=False):
        """
        Function to clear up (flush) the VISA message queue of the AWG
        instrument. Reads all messages in the the queue.

        Args:
            verbose (Bool): If True, the read messages are printed.
                Default: False.
        """
        original_timeout = self.visa_handle.timeout
        self.visa_handle.timeout = 1000  # 1 second as VISA counts in ms
        gotexception = False
        while not gotexception:
            try:
                message = self.visa_handle.read()
                if verbose:
                    print(message)
            except VisaIOError:
                gotexception = True
        self.visa_handle.timeout = original_timeout

