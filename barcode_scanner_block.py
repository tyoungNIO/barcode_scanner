from .hid_map import hid_map
from binascii import hexlify
from threading import current_thread
from time import sleep
from nio import GeneratorBlock, Signal
from nio.properties import StringProperty, VersionProperty
from nio.util.runner import RunnerStatus
from nio.util.threading import spawn


class BarcodeScanner(GeneratorBlock):

    device = StringProperty(title='Device',
                            default='/dev/hidraw0',
                            advanced=True)
    version = VersionProperty('0.1.3')

    delimiter = b'\x28'  # carriage return
    reconnect_interval = 1

    def __init__(self):
        super().__init__()
        self.file_descriptor = None
        self._kill = None
        self._thread = None

    def start(self):
        super().start()
        spawn(self._connect)

    def stop(self):
        if self.file_descriptor:
            self._disconnect()
        super().stop()

    def _connect(self):
        self.logger.debug('Opening HID Device {}'.format(self.device()))
        while not self.file_descriptor:
            try:
                self.file_descriptor = open(self.device(), 'rb')
            except Exception:
                if not self.status.is_set(RunnerStatus.warning):
                    self.set_status('warning')
                msg = 'Unable to open HID Device, trying again in {} seconds'
                self.logger.error(msg.format(self.reconnect_interval))
                sleep(self.reconnect_interval)
        self._kill = False
        self._thread = spawn(self._delimited_reader)
        self.set_status('ok')

    def _delimited_reader(self):
        thread_id = current_thread().name
        self.logger.debug('Reader thread {} spawned'.format(thread_id))
        buffer = []
        while not self._kill:
            try:
                new_byte = self.file_descriptor.read(1)
            except Exception:
                if not self.status.is_set(RunnerStatus.warning):
                    self.set_status('warning')
                self.logger.exception('Read operation from HID Device failed')
                self._disconnect()
                self._connect()
                break
            if new_byte == self.delimiter:
                try:
                    barcode = self._decode_buffer(buffer)
                except Exception:
                    self.logger.exception('Failed to decode barcode!')
                    barcode = None
                signal_dict = {'barcode': barcode}
                self.notify_signals([Signal(signal_dict)])
                buffer = []
                continue
            buffer.append(new_byte)
        self.logger.debug('Reader thread {} completed'.format(thread_id))

    def _decode_buffer(self, buffer):
        self.logger.debug('decoding {} bytes'.format(len(buffer)))
        self.logger.debug('buffer: {}'.format([hexlify(b) for b in buffer]))
        shift = False
        output = ''
        zeroes = 0
        for b in buffer:
            if b == b'\x00':
                zeroes += 1
                # If we've read more than 2 straight 0s then reset our shift
                # Sometimes rogue shift keys seem to come through when they
                # aren't actually shifting anything
                if zeroes > 2:
                    shift = False
                continue
            zeroes = 0
            if b == b'\x02':  # shift the next character
                shift = True
                continue
            output += hid_map[shift][ord(b)]
            shift = False
        return output

    def _disconnect(self):
        self.logger.debug('closing HID Device')
        self._kill = True
        self.file_descriptor.close()
        self.file_descriptor = None
