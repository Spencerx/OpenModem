from __future__ import print_function
from time import sleep
import sys
import serial
import threading
import time
import argparse
import struct

class RNS():
	@staticmethod
	def log(msg):
		logtimefmt   = "%Y-%m-%d %H:%M:%S"
		timestamp = time.time()
		logstring = "["+time.strftime(logtimefmt)+"] "+msg
		print(logstring)

	@staticmethod
	def hexrep(data, delimit=True):
		delimiter = ":"
		if not delimit:
			delimiter = ""
		hexrep = delimiter.join("{:02x}".format(ord(c)) for c in data)
		return hexrep

	@staticmethod
	def prettyhexrep(data):
		delimiter = ""
		hexrep = "<"+delimiter.join("{:02x}".format(ord(c)) for c in data)+">"
		return hexrep

class Interface:
    IN  = False
    OUT = False
    FWD = False
    RPT = False
    name = None

    def __init__(self):
        pass

class KISS():
	FEND			= chr(0xC0)
	FESC			= chr(0xDB)
	TFEND			= chr(0xDC)
	TFESC			= chr(0xDD)
	CMD_UNKNOWN		= chr(0xFE)
	CMD_DATA		= chr(0x00)
	CMD_TXDELAY		= chr(0x01)
	CMD_P			= chr(0x02)
	CMD_SLOTTIME	= chr(0x03)
	CMD_TXTAIL		= chr(0x04)
	CMD_FULLDUPLEX	= chr(0x05)
	CMD_SETHARDWARE	= chr(0x06)
	CMD_READY       = chr(0x0F)
	CMD_AUDIO_PEAK  = chr(0x12)
	CMD_EN_DIAGS    = chr(0x13)
	CMD_RETURN		= chr(0xFF)

	@staticmethod
	def escape(data):
		data = data.replace(chr(0xdb), chr(0xdb)+chr(0xdd))
		data = data.replace(chr(0xc0), chr(0xdb)+chr(0xdc))
		return data

class KISSInterface(Interface):
	MAX_CHUNK = 32768

	owner    = None
	port     = None
	speed    = None
	databits = None
	parity   = None
	stopbits = None
	serial   = None

	def __init__(self, owner, name, port, speed, databits, parity, stopbits, preamble, txtail, persistence, slottime, flow_control):
		self.serial   = None
		self.owner    = owner
		self.name     = name
		self.port     = port
		self.speed    = speed
		self.databits = databits
		self.parity   = serial.PARITY_NONE
		self.stopbits = stopbits
		self.timeout  = 100
		self.online   = False

		self.packet_queue    = []
		self.flow_control = flow_control
		self.interface_ready = False

		self.preamble    = preamble if preamble != None else 350;
		self.txtail      = txtail if txtail != None else 20;
		self.persistence = persistence if persistence != None else 64;
		self.slottime    = slottime if slottime != None else 20;

		if parity.lower() == "e" or parity.lower() == "even":
			self.parity = serial.PARITY_EVEN

		if parity.lower() == "o" or parity.lower() == "odd":
			self.parity = serial.PARITY_ODD

		try:
			RNS.log("Opening serial port "+self.port+"...")
			self.serial = serial.Serial(
				port = self.port,
				baudrate = self.speed,
				bytesize = self.databits,
				parity = self.parity,
				stopbits = self.stopbits,
				xonxoff = False,
				rtscts = False,
				timeout = 0,
				inter_byte_timeout = None,
				write_timeout = None,
				dsrdtr = False,
			)
		except Exception as e:
			RNS.log("Could not open serial port "+self.port)
			raise e

		if self.serial.is_open:
			# Allow time for interface to initialise before config
			sleep(2.0)
			thread = threading.Thread(target=self.readLoop)
			thread.setDaemon(True)
			thread.start()
			self.online = True
			RNS.log("Serial port "+self.port+" is now open")
			RNS.log("Configuring KISS interface parameters...")
			self.setPreamble(self.preamble)
			self.setTxTail(self.txtail)
			self.setPersistence(self.persistence)
			self.setSlotTime(self.slottime)
			self.setFlowControl(self.flow_control)
			self.interface_ready = True
			RNS.log("KISS interface configured")
		else:
			raise IOError("Could not open serial port")


	def askForPeak(self):
		kiss_command = KISS.FEND+KISS.CMD_AUDIO_PEAK+chr(0x01)+KISS.FEND
		written = self.serial.write(kiss_command)
		if written != len(kiss_command):
			raise IOError("Could not ask for peak data")

	def displayPeak(self, peak):
		peak_value = struct.unpack("b", peak)
		#RNS.log("Peak is: "+RNS.hexrep(peak))
		RNS.log("Peak is: "+str(peak_value[0]))

	def setPreamble(self, preamble):
		preamble_ms = preamble
		preamble = int(preamble_ms / 10)
		if preamble < 0:
			preamble = 0
		if preamble > 255:
			preamble = 255

		RNS.log("Setting preamble to "+str(preamble)+" "+chr(preamble))
		kiss_command = KISS.FEND+KISS.CMD_TXDELAY+chr(preamble)+KISS.FEND
		written = self.serial.write(kiss_command)
		if written != len(kiss_command):
			raise IOError("Could not configure KISS interface preamble to "+str(preamble_ms)+" (command value "+str(preamble)+")")

	def setTxTail(self, txtail):
		txtail_ms = txtail
		txtail = int(txtail_ms / 10)
		if txtail < 0:
			txtail = 0
		if txtail > 255:
			txtail = 255

		kiss_command = KISS.FEND+KISS.CMD_TXTAIL+chr(txtail)+KISS.FEND
		written = self.serial.write(kiss_command)
		if written != len(kiss_command):
			raise IOError("Could not configure KISS interface TX tail to "+str(txtail_ms)+" (command value "+str(txtail)+")")

	def setPersistence(self, persistence):
		if persistence < 0:
			persistence = 0
		if persistence > 255:
			persistence = 255

		kiss_command = KISS.FEND+KISS.CMD_P+chr(persistence)+KISS.FEND
		written = self.serial.write(kiss_command)
		if written != len(kiss_command):
			raise IOError("Could not configure KISS interface persistence to "+str(persistence))

	def setSlotTime(self, slottime):
		slottime_ms = slottime
		slottime = int(slottime_ms / 10)
		if slottime < 0:
			slottime = 0
		if slottime > 255:
			slottime = 255

		kiss_command = KISS.FEND+KISS.CMD_SLOTTIME+chr(slottime)+KISS.FEND
		written = self.serial.write(kiss_command)
		if written != len(kiss_command):
			raise IOError("Could not configure KISS interface slot time to "+str(slottime_ms)+" (command value "+str(slottime)+")")

	def setFlowControl(self, flow_control):
		kiss_command = KISS.FEND+KISS.CMD_READY+chr(0x01)+KISS.FEND
		written = self.serial.write(kiss_command)
		if written != len(kiss_command):
			if (flow_control):
				raise IOError("Could not enable KISS interface flow control")
			else:
				raise IOError("Could not enable KISS interface flow control")

	def enableDiagnostics(self):
		kiss_command = KISS.FEND+KISS.CMD_EN_DIAGS+chr(0x01)+KISS.FEND
		written = self.serial.write(kiss_command)
		if written != len(kiss_command):
			raise IOError("Could not enable KISS interface diagnostics")

	def disableDiagnostics(self):
		kiss_command = KISS.FEND+KISS.CMD_EN_DIAGS+chr(0x00)+KISS.FEND
		written = self.serial.write(kiss_command)
		if written != len(kiss_command):
			raise IOError("Could not disable KISS interface diagnostics")
			


	def processIncoming(self, data):
		RNS.log("Decoded packet");


	def processOutgoing(self,data):
		pass

	def queue(self, data):
		pass

	def process_queue(self):
		pass

	def readLoop(self):
		try:
			in_frame = False
			escape = False
			command = KISS.CMD_UNKNOWN
			data_buffer = ""
			last_read_ms = int(time.time()*1000)

			while self.serial.is_open:
				if self.serial.in_waiting:
					byte = self.serial.read(1)
					last_read_ms = int(time.time()*1000)

					if (in_frame and byte == KISS.FEND and command == KISS.CMD_DATA):
						in_frame = False
						self.processIncoming(data_buffer)
					elif (byte == KISS.FEND):
						in_frame = True
						command = KISS.CMD_UNKNOWN
						data_buffer = ""
					elif (in_frame and len(data_buffer) < 611):
						if (len(data_buffer) == 0 and command == KISS.CMD_UNKNOWN):
							command = byte
						elif (command == KISS.CMD_DATA):
							if (byte == KISS.FESC):
								escape = True
							else:
								if (escape):
									if (byte == KISS.TFEND):
										byte = KISS.FEND
									if (byte == KISS.TFESC):
										byte = KISS.FESC
									escape = False
								data_buffer = data_buffer+byte
						elif (command == KISS.CMD_AUDIO_PEAK):
							self.displayPeak(byte)
				else:
					time_since_last = int(time.time()*1000) - last_read_ms
					if len(data_buffer) > 0 and time_since_last > self.timeout:
			 			data_buffer = ""
			 			in_frame = False
			 			command = KISS.CMD_UNKNOWN
			 			escape = False
			 		sleep(0.08)
			 		self.askForPeak()

		except Exception as e:
			self.online = False
			RNS.log("A serial port error occurred, the contained exception was: "+str(e))
			RNS.log("The interface "+str(self.name)+" is now offline. Restart Reticulum to attempt reconnection.")

	def __str__(self):
		return "KISSInterface["+self.name+"]"

if __name__ == "__main__":
		parser = argparse.ArgumentParser(description="OpenModem Audio Level Monitor")
		parser.add_argument("port", nargs="?", default=None, help="serial port where RNode is attached", type=str)
		args = parser.parse_args()

		if args.port:
			kiss_interface = KISSInterface(None, "OpenModem Interface", args.port, 115200, 8, "N", 1, 150, 10, 255, 20, False)
			kiss_interface.enableDiagnostics()
			raw_input();

		else:
			print("")
			parser.print_help()
			print("")
			exit()
